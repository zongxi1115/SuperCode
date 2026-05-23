from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent import AgentLLMConfig

CONFIG_DIRECTORY_NAME = ".supercode"
CONFIG_FILE_NAME = "model-providers.json"


def config_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / CONFIG_FILE_NAME


def infer_provider_from_url(base_url: str) -> str:
    url_lower = base_url.lower()
    if "anthropic" in url_lower:
        return "anthropic"
    if "openai" in url_lower:
        return "openai"
    if "deepseek" in url_lower:
        return "deepseek"
    if "dashscope" in url_lower or "aliyun" in url_lower or "qwen" in url_lower:
        return "alibaba-cn"
    if "google" in url_lower or "gemini" in url_lower:
        return "google"
    if "groq" in url_lower:
        return "groq"
    if "mistral" in url_lower:
        return "mistral"
    if "xai" in url_lower:
        return "xai"
    if "openrouter" in url_lower:
        return "openrouter"
    if "together" in url_lower:
        return "togetherai"
    if "fireworks" in url_lower:
        return "fireworks-ai"
    if "cerebras" in url_lower:
        return "cerebras"
    return "openrouter"


def normalize_model_names(values: list[str] | tuple[str, ...] | set[str] | None) -> list[str]:
    if not values:
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        for part in re.split(r"[\r\n,]+", str(raw_value)):
            candidate = part.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _normalize_provider_payload(raw: dict[str, Any]) -> dict[str, Any]:
    base_url = str(raw.get("baseUrl", "")).strip().rstrip("/")
    provider_name = str(raw.get("name", "")).strip() or "未命名供应商"
    provider_id = str(raw.get("id", "")).strip() or uuid.uuid4().hex
    return {
        "id": provider_id,
        "name": provider_name,
        "baseUrl": base_url,
        "apiKey": str(raw.get("apiKey", "")).strip(),
        "models": normalize_model_names(raw.get("models")),
        "provider": str(raw.get("provider", "")).strip() or infer_provider_from_url(base_url),
    }


def load_ui_model_providers(root: Path) -> list[dict[str, Any]]:
    path = config_store_path(root)
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    providers = payload.get("providers", [])
    if not isinstance(providers, list):
        return []
    return [_normalize_provider_payload(provider) for provider in providers if isinstance(provider, dict)]


def save_ui_model_providers(root: Path, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_provider_payload(provider) for provider in providers]
    path = config_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"providers": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def scan_env_model_sources(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for env_path in sorted(root.glob(".env*")):
        if not env_path.is_file():
            continue
        try:
            text = env_path.read_text(encoding="utf-8")
        except OSError:
            continue

        model_match = re.search(r"^SC_AGENT_MODEL\s*=\s*(.+)$", text, re.MULTILINE)
        base_url_match = re.search(r"^SC_AGENT_BASE_URL\s*=\s*(.+)$", text, re.MULTILINE)
        if not model_match:
            continue

        model_name = model_match.group(1).strip().strip("'\"")
        if not model_name:
            continue

        base_url = base_url_match.group(1).strip().strip("'\"") if base_url_match else ""
        config_ref = f"env::{env_path.name}"
        results.append(
            {
                "id": config_ref,
                "name": model_name,
                "model": model_name,
                "provider": infer_provider_from_url(base_url),
                "envFile": config_ref,
                "label": f"{model_name}" if env_path.name == ".env" else f"{model_name} ({env_path.name})",
                "sourceType": "env",
                "sourceLabel": env_path.name,
                "readOnly": True,
            }
        )

    return results


def build_ui_model_sources(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider in load_ui_model_providers(root):
        for model_name in provider["models"]:
            config_ref = f"ui::{provider['id']}::{model_name}"
            results.append(
                {
                    "id": config_ref,
                    "name": model_name,
                    "model": model_name,
                    "provider": provider["provider"],
                    "envFile": config_ref,
                    "label": f"{model_name} ({provider['name']})",
                    "sourceType": "ui",
                    "sourceLabel": provider["name"],
                    "readOnly": False,
                }
            )
    return results


def list_model_options(root: Path) -> list[dict[str, Any]]:
    return [*scan_env_model_sources(root), *build_ui_model_sources(root)]


def resolve_model_option(
    root: Path,
    model_name: str | None = None,
    env_file: str | None = None,
) -> dict[str, Any]:
    models = list_model_options(root)
    if model_name:
        target = next(
            (
                model
                for model in models
                if model["id"] == model_name or model["model"] == model_name
            ),
            None,
        )
        if target is None:
            raise ValueError("未找到对应的模型配置")
        return target

    if env_file:
        target = next(
            (
                model
                for model in models
                if model["envFile"] == env_file or model["sourceLabel"] == env_file
            ),
            None,
        )
        if target is None:
            raise ValueError("未找到对应的模型配置")
        return target

    raise ValueError("必须提供 model。")


def build_agent_config(root: Path, model_ref: str | None = None) -> tuple[AgentLLMConfig, str]:
    normalized_ref = model_ref
    if normalized_ref and normalized_ref.endswith(".env") and not normalized_ref.startswith("env::"):
        normalized_ref = f"env::{normalized_ref}"

    if normalized_ref is None:
        return AgentLLMConfig.from_env(root / ".env"), "env::.env"

    if normalized_ref.startswith("env::"):
        env_name = normalized_ref.split("::", 1)[1]
        return AgentLLMConfig.from_env(root / env_name), normalized_ref

    if normalized_ref.startswith("ui::"):
        _, provider_id, model_name = normalized_ref.split("::", 2)
        provider = next(
            (item for item in load_ui_model_providers(root) if item["id"] == provider_id),
            None,
        )
        if provider is None:
            raise ValueError("未找到对应的可视化供应商配置")
        return (
            AgentLLMConfig.from_mapping(
                {
                    "SC_AGENT_API_KEY": provider["apiKey"],
                    "SC_AGENT_BASE_URL": provider["baseUrl"],
                    "SC_AGENT_MODEL": model_name,
                }
            ),
            normalized_ref,
        )

    return build_agent_config(root, f"env::{normalized_ref}")


def discover_provider_models(provider_payload: dict[str, Any]) -> list[str]:
    provider = _normalize_provider_payload(provider_payload)
    if not provider["baseUrl"]:
        raise ValueError("请先填写 Base URL")
    if not provider["apiKey"]:
        raise ValueError("请先填写 API Key")

    request = Request(
        f"{provider['baseUrl'].rstrip('/')}/models",
        headers={
            "Authorization": f"Bearer {provider['apiKey']}",
            "Accept": "application/json",
            "User-Agent": "SuperCode/1.0",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise ValueError(detail or f"拉取模型列表失败: HTTP {exc.code}") from exc
    except URLError as exc:
        raise ValueError(f"拉取模型列表失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ValueError("拉取模型列表超时") from exc

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("模型接口返回格式不正确")

    models: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", "")).strip()
        if model_id:
            models.append(model_id)

    normalized = normalize_model_names(models)
    if not normalized:
        raise ValueError("接口返回为空，未发现可用模型")
    return normalized
