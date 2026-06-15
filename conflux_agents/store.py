from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from conflux_agents.config import ConfluxConfig

CONFIG_DIRECTORY_NAME = ".supercode"
CONFLUX_CONFIG_FILE_NAME = "conflux_config.json"


def conflux_config_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / CONFLUX_CONFIG_FILE_NAME


class ConfluxConfigStore:
    """负责 Conflux Agents 配置的磁盘读写。"""

    def __init__(self, root: str | Path | None = None, path: str | Path | None = None) -> None:
        if path is not None:
            self.path = Path(path).expanduser().resolve()
            return

        if root is None:
            from fastapi_app.app_config import APP_DATA_ROOT

            root = APP_DATA_ROOT

        self.path = conflux_config_store_path(Path(root).expanduser().resolve())

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> ConfluxConfig | None:
        if not self.path.exists():
            return None

        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"读取 Conflux 配置失败：{self.path}") from exc

        if not raw_text.strip():
            return None

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Conflux 配置 JSON 格式错误：{self.path}，{exc.msg}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Conflux 配置文件顶层必须是 JSON object：{self.path}")

        try:
            return ConfluxConfig.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"Conflux 配置内容不符合结构：{self.path}\n{exc}") from exc

    def save(self, config: ConfluxConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Conflux 配置只保存 ui::<provider_id>::<model_id> 这类模型引用和专长描述，
        # 不包含 API key、Base URL 等敏感明文；真实密钥仍由 SecureConfigStore 加密管理。
        # 因此这里沿用非敏感设置的 JSON 文件存储，避免把 Conflux 的独立配置混入模型密钥表。
        payload = config.model_dump(mode="json")
        raw_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")

        try:
            tmp_path.write_text(raw_text, encoding="utf-8")
            tmp_path.replace(self.path)
        except OSError as exc:
            raise RuntimeError(f"保存 Conflux 配置失败：{self.path}") from exc
