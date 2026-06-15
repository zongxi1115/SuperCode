from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


def _new_config_id() -> str:
    return uuid.uuid4().hex


class ConfluxSpecialistConfig(BaseModel):
    """单个 Conflux 子智能体的持久化配置。"""

    id: str = Field(
        default_factory=_new_config_id,
        description="子智能体的唯一标识，由 uuid4 默认生成，用于前端列表更新和后续任务路由定位。",
    )
    name: str = Field(
        description="用户给子智能体起的展示名称，例如“前端专家”或“Python 大师”。",
    )
    model_ref: str = Field(
        description=(
            "子智能体使用的全局模型引用，沿用 SuperCode 现有模型引用规范；"
            "UI 模型通常形如 ui::<provider_id>::<model_id>。"
        ),
    )
    token_budget: int = Field(
        default=50_000,
        ge=1,
        description="子智能体单次执行的 token 预算，用于后续运行时限制它能消耗的上下文与输出规模。",
    )
    specialty: str = Field(
        description="用户填写的自然语言专长描述，用来告诉协调者这个子智能体适合处理哪些任务。",
    )

    @field_validator("id", "name", "model_ref", "specialty")
    @classmethod
    def _require_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conflux 子智能体配置中的文本字段不能为空。")
        return normalized


class ConfluxOrchestratorConfig(BaseModel):
    """Conflux 协调者的持久化配置。"""

    model_ref: str = Field(
        description=(
            "协调者使用的全局模型引用，沿用 SuperCode 现有模型引用规范；"
            "UI 模型通常形如 ui::<provider_id>::<model_id>。"
        ),
    )
    token_budget: int = Field(
        default=100_000,
        ge=1,
        description="协调者单次任务的 token 预算，用于后续拆分任务、审计 diff 和合并阶段的上下文控制。",
    )

    @field_validator("model_ref")
    @classmethod
    def _require_model_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Conflux 协调者模型引用不能为空。")
        return normalized


class ConfluxConfig(BaseModel):
    """完整的 Conflux Agents 模式配置。"""

    orchestrator: ConfluxOrchestratorConfig = Field(
        description="协调者配置，决定由哪个模型负责拆任务、派发、审计 diff 和合并代码。",
    )
    specialists: list[ConfluxSpecialistConfig] = Field(
        description="子智能体配置列表，至少需要 1 个，协调者会根据专长描述把任务派发给它们。",
    )
    require_user_review_per_step: bool = Field(
        default=False,
        description="是否要求每个子智能体完成一步后都由用户 review；默认关闭，适合减少长任务打断。",
    )
    require_orchestrator_diff_review: bool = Field(
        default=True,
        description="只读安全底线：协调者合并前必须执行一次 git diff review，用户不能关闭。",
    )
    max_dispatch_depth: int = Field(
        default=2,
        description=(
            "系统硬上限：最多允许 orchestrator -> A -> B 这一层级的再派发，"
            "B 不能继续派发，用户不能修改。"
        ),
    )

    @field_validator("specialists")
    @classmethod
    def _require_specialists(cls, value: list[ConfluxSpecialistConfig]) -> list[ConfluxSpecialistConfig]:
        if not value:
            raise ValueError("Conflux 至少需要配置 1 个子智能体。")
        return value

    @field_validator("require_orchestrator_diff_review")
    @classmethod
    def _require_orchestrator_diff_review(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("require_orchestrator_diff_review 是只读安全底线，不能关闭。")
        return value

    @field_validator("max_dispatch_depth")
    @classmethod
    def _require_system_dispatch_depth(cls, value: int) -> int:
        if value != 2:
            raise ValueError("max_dispatch_depth 是系统硬上限，当前固定为 2。")
        return value
