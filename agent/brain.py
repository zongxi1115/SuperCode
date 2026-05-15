from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .schema import AgentState


@dataclass(slots=True)
class BrainDecision:
    """brain 在当前步骤做出的决策。

    `action` 目前只支持两种：
    1. `tool`：调用某个工具
    2. `final`：直接产出最终结果
    """

    action: str
    thought: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None

    @classmethod
    def call_tool(
        cls,
        thought: str,
        tool_name: str,
        tool_arguments: dict[str, Any] | None = None,
    ) -> "BrainDecision":
        """创建一个“调用工具”的决策。"""

        return cls(
            action="tool",
            thought=thought,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
        )

    @classmethod
    def finish(cls, thought: str, final_answer: str) -> "BrainDecision":
        """创建一个“结束并返回答案”的决策。"""

        return cls(action="final", thought=thought, final_answer=final_answer)


@dataclass(slots=True)
class BrainStreamingUpdate:
    """记录 brain 在流式生成决策时的增量状态。"""

    raw_output: str
    action: str | None = None
    thought: str | None = None
    tool_name: str | None = None
    final_answer: str | None = None


class AgentBrain(ABC):
    """智能体决策接口。

    你可以把它理解成“轻量版大脑”：
    给它当前状态和可用工具描述，它决定下一步做什么。
    后面若需要接入真实大模型，只要实现同样接口即可。
    """

    @abstractmethod
    def decide(
        self,
        state: AgentState,
        tool_descriptions: dict[str, str],
        on_stream: Callable[[BrainStreamingUpdate], None] | None = None,
    ) -> BrainDecision:
        """根据当前状态决定下一步动作。"""
