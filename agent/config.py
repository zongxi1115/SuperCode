from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AgentLLMConfig:
    """真实 API 调用配置。

    这里使用 OpenAI 兼容接口的常见字段，目的是让框架能接 OpenAI，
    也能接很多采用同类协议的模型服务。
    """

    api_key: str
    base_url: str
    model: str
    timeout: int = 60
    max_retries: int = 2
    include_thoughts_in_context: bool = False

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "AgentLLMConfig":
        """从 `.env` 和系统环境变量中读取配置。"""

        env_values = read_dotenv_values(env_path)
        return cls.from_mapping(env_values)

    @classmethod
    def from_mapping(cls, env_values: dict[str, str]) -> "AgentLLMConfig":
        """从一组键值映射中读取配置。"""

        api_key = env_values.get("SC_AGENT_API_KEY", os.getenv("SC_AGENT_API_KEY", "")).strip()
        base_url = env_values.get("SC_AGENT_BASE_URL", os.getenv("SC_AGENT_BASE_URL", "")).strip()
        model = env_values.get("SC_AGENT_MODEL", os.getenv("SC_AGENT_MODEL", "")).strip()
        timeout = int(env_values.get("SC_AGENT_TIMEOUT", os.getenv("SC_AGENT_TIMEOUT", "60")).strip())
        max_retries = int(env_values.get("SC_AGENT_MAX_RETRIES", os.getenv("SC_AGENT_MAX_RETRIES", "2")).strip())
        include_thoughts_in_context = _parse_bool(
            env_values.get(
                "SC_AGENT_INCLUDE_THOUGHTS_IN_CONTEXT",
                os.getenv("SC_AGENT_INCLUDE_THOUGHTS_IN_CONTEXT", "false"),
            )
        )

        missing_fields: list[str] = []
        if not api_key:
            missing_fields.append("SC_AGENT_API_KEY")
        if not base_url:
            missing_fields.append("SC_AGENT_BASE_URL")
        if not model:
            missing_fields.append("SC_AGENT_MODEL")

        if missing_fields:
            joined = ", ".join(missing_fields)
            raise ValueError(
                "缺少真实 API 配置，请先复制 `.env.example` 为 `.env`，"
                f"并补齐这些字段: {joined}"
            )

        placeholder_values = {
            "your_api_key_here",
            "your_model_name_here",
        }
        if api_key in placeholder_values or model in placeholder_values:
            raise ValueError("`.env` 里还是占位值，请先替换成你自己的真实接口配置。")

        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout=timeout,
            max_retries=max(0, max_retries),
            include_thoughts_in_context=include_thoughts_in_context,
        )


def load_dotenv(env_path: str | Path = ".env") -> None:
    """读取一个简单的 `.env` 文件。

    这里只支持最常见的 `KEY=VALUE` 形式，足够覆盖当前 demo。
    如果系统环境变量里已经存在同名值，则优先保留系统环境变量。
    """

    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        env_key = key.strip()
        env_value = _strip_env_value(value.strip())

        if env_key and env_key not in os.environ:
            os.environ[env_key] = env_value


def read_dotenv_values(env_path: str | Path = ".env") -> dict[str, str]:
    """读取 `.env` 文件并返回键值，但不写入全局环境变量。"""

    path = Path(env_path)
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        env_key = key.strip()
        env_value = _strip_env_value(value.strip())
        if env_key:
            values[env_key] = env_value
    return values


def _strip_env_value(value: str) -> str:
    """去掉 `.env` 值两端的引号。"""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
