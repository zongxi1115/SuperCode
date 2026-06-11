from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent import AgentLLMConfig
from fastapi_app.secure_config_store import get_secure_config_store

CONFIG_DIRECTORY_NAME = ".supercode"
CONFIG_FILE_NAME = "model-providers.json"
MODEL_CONTEXT_TOKEN_KEYS = {
    "context_length",
    "contextLength",
    "context_window",
    "contextWindow",
    "max_context_length",
    "maxContextLength",
    "max_context_tokens",
    "maxContextTokens",
    "max_input_tokens",
    "maxInputTokens",
    "input_token_limit",
    "inputTokenLimit",
}


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


def _model_name_from_payload(value: dict[str, Any]) -> str:
    return str(value.get("id") or value.get("name") or value.get("model") or "").strip()


def _context_window_for_model(model_id: str, payload: object) -> int:
    return extract_model_context_tokens(payload) or _infer_model_context_window(model_id)


def _infer_model_context_window(model_name: str) -> int:
    normalized = model_name.lower()
    if "claude" in normalized:
        return 200_000
    if "gpt-4.1" in normalized:
        return 1_047_576
    if "gpt-5-chat" in normalized:
        return 128_000
    if "gpt-5.5" in normalized:
        return 1_050_000
    if "gpt-5.4-mini" in normalized or "gpt-5.4-nano" in normalized:
        return 400_000
    if "gpt-5.4" in normalized:
        return 1_050_000
    if "gpt-5" in normalized:
        return 400_000
    if "qwen" in normalized:
        return 128_000
    if "gpt-4o-mini" in normalized or "gpt-4o" in normalized:
        return 128_000
    if "deepseek" in normalized:
        return 64_000
    return 32_000


def _normalize_model_records(values: list[Any] | tuple[Any, ...] | set[Any] | None) -> list[dict[str, Any]]:
    if not values:
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_value in values:
        if not isinstance(raw_value, dict):
            continue
        model_id = _model_name_from_payload(raw_value)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        records.append(
            {
                "id": model_id,
                "contextWindow": _context_window_for_model(model_id, raw_value),
            }
        )
    return records


def _normalize_provider_payload(raw: dict[str, Any]) -> dict[str, Any]:
    base_url = str(raw.get("baseUrl", "")).strip().rstrip("/")
    provider_name = str(raw.get("name", "")).strip() or "未命名供应商"
    provider_id = str(raw.get("id", "")).strip() or uuid.uuid4().hex
    return {
        "id": provider_id,
        "name": provider_name,
        "baseUrl": base_url,
        "apiKey": str(raw.get("apiKey", "")).strip(),
        "models": _normalize_model_records(raw.get("models")),
        "provider": str(raw.get("provider", "")).strip() or infer_provider_from_url(base_url),
        "apiMode": normalize_api_mode(raw.get("apiMode")),
    }


def load_ui_model_providers(root: Path) -> list[dict[str, Any]]:
    """加载供应商配置；首次启动时从旧 JSON 迁移到加密数据库。"""
    secure_store = get_secure_config_store(root)
    providers = secure_store.load_providers()
    path = config_store_path(root)
    if not providers and path.exists():
        secure_store.migrate_from_json_file(path)
        providers = secure_store.load_providers()
    return providers


def save_ui_model_providers(
    root: Path,
    providers: list[dict[str, Any]],
    *,
    refresh_context: bool = True,
) -> list[dict[str, Any]]:
    """保存供应商配置到数据库（加密存储）"""
    normalized = [_normalize_provider_payload(provider) for provider in providers]
    if refresh_context:
        normalized = refresh_provider_context_windows(normalized)
    secure_store = get_secure_config_store(root)
    secure_store.save_providers(normalized)
    return normalized


def scan_env_model_sources(root: Path) -> list[dict[str, Any]]:
    # `.env` 不再参与模型发现，避免旧配置干扰 UI 供应商顺序与默认选择。
    return []


def build_ui_model_sources(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for provider in load_ui_model_providers(root):
        for model in provider["models"]:
            model_name = str(model.get("id") or "").strip()
            if not model_name:
                continue
            config_ref = f"ui::{provider['id']}::{model_name}"
            results.append(
                {
                    "id": config_ref,
                    "name": model_name,
                    "model": model_name,
                    "provider": provider["provider"],
                    "apiMode": provider["apiMode"],
                    "envFile": config_ref,
                    "label": f"{model_name} ({provider['name']})",
                    "sourceType": "ui",
                    "sourceLabel": provider["name"],
                    "contextWindow": extract_model_context_tokens(model),
                    "readOnly": False,
                }
            )
    return results


def list_model_options(root: Path) -> list[dict[str, Any]]:
    return [*scan_env_model_sources(root), *build_ui_model_sources(root)]


def get_default_model_option(root: Path) -> dict[str, Any] | None:
    models = list_model_options(root)
    return models[0] if models else None


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

    default_model = models[0] if models else None
    if default_model is not None:
        return default_model
    raise ValueError("未配置可用模型，请先在设置里添加至少一个供应商模型。")


def build_agent_config(root: Path, model_ref: str | None = None) -> tuple[AgentLLMConfig, str]:
    normalized_ref = model_ref
    if normalized_ref and normalized_ref.endswith(".env") and not normalized_ref.startswith("env::"):
        normalized_ref = f"env::{normalized_ref}"

    if normalized_ref is None:
        default_model = get_default_model_option(root)
        if default_model is None:
            raise ValueError("未配置可用模型，请先在设置里添加至少一个供应商模型。")
        return build_agent_config(root, str(default_model["envFile"]))

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
                    "SC_AGENT_API_MODE": provider["apiMode"],
                }
            ),
            normalized_ref,
        )

    return build_agent_config(root, f"env::{normalized_ref}")


def _fetch_provider_model_records(provider_payload: dict[str, Any]) -> list[dict[str, Any]]:
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
    return [item for item in data if isinstance(item, dict)]


def discover_provider_model_catalog(provider_payload: dict[str, Any]) -> dict[str, Any]:
    data = _fetch_provider_model_records(provider_payload)
    models = _model_records_from_provider_records(data)
    if not models:
        raise ValueError("接口返回为空，未发现可用模型")
    return {"models": models}


def _model_records_from_provider_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        model_id = _model_name_from_payload(record)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            {
                "id": model_id,
                "contextWindow": _context_window_for_model(model_id, record),
            }
        )
    return models


def refresh_provider_context_windows(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not providers:
        return []
    refreshed: list[dict[str, Any]] = [dict(provider) for provider in providers]
    with ThreadPoolExecutor(max_workers=min(8, len(refreshed))) as executor:
        future_by_index = {
            executor.submit(_refresh_single_provider_context_window, provider): index
            for index, provider in enumerate(refreshed)
        }
        for future in as_completed(future_by_index):
            index = future_by_index[future]
            try:
                refreshed[index] = future.result()
            except Exception:
                refreshed[index] = refreshed[index]
    return refreshed


def refresh_ui_model_context_cache(root: Path) -> list[dict[str, Any]]:
    providers = load_ui_model_providers(root)
    return save_ui_model_providers(root, providers, refresh_context=True)


def _refresh_single_provider_context_window(provider: dict[str, Any]) -> dict[str, Any]:
    normalized_provider = _normalize_provider_payload(provider)
    if not normalized_provider["models"]:
        return normalized_provider
    try:
        records = _fetch_provider_model_records(normalized_provider)
    except ValueError:
        return normalized_provider
    records_by_id = {_model_name_from_payload(item): item for item in records}
    refreshed_models: list[dict[str, Any]] = []
    for model in normalized_provider["models"]:
        model_id = str(model.get("id") or "").strip()
        record = records_by_id.get(model_id)
        refreshed_models.append(
            {
                "id": model_id,
                "contextWindow": _context_window_for_model(model_id, record or model),
            }
        )
    return {**normalized_provider, "models": refreshed_models}


def extract_model_context_tokens(model_payload: object) -> int | None:
    if not isinstance(model_payload, dict):
        return None
    for key in MODEL_CONTEXT_TOKEN_KEYS:
        value = _coerce_context_tokens(model_payload.get(key))
        if value is not None:
            return value
    for value in model_payload.values():
        if isinstance(value, dict):
            nested = extract_model_context_tokens(value)
            if nested is not None:
                return nested
    return None


def resolve_model_context_tokens(root: Path, model_ref: str | None) -> int | None:
    if not model_ref:
        return None
    normalized_ref = model_ref
    if normalized_ref.endswith(".env") and not normalized_ref.startswith("env::"):
        normalized_ref = f"env::{normalized_ref}"
    if not normalized_ref.startswith("ui::"):
        return None

    try:
        _, provider_id, model_name = normalized_ref.split("::", 2)
    except ValueError:
        return None
    provider = next(
        (item for item in load_ui_model_providers(root) if item["id"] == provider_id),
        None,
    )
    if provider is None:
        return None
    # Keep session creation off the network; explicit model discovery owns /models calls.
    for model in provider["models"]:
        if str(model.get("id") or "").strip() == model_name:
            return extract_model_context_tokens(model)
    return None


def _coerce_context_tokens(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        tokens = value
    elif isinstance(value, float):
        tokens = int(value)
    elif isinstance(value, str):
        compact = value.strip().replace(",", "").replace("_", "")
        if not compact:
            return None
        try:
            tokens = int(float(compact))
        except ValueError:
            return None
    else:
        return None
    return tokens if tokens > 0 else None


def normalize_api_mode(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"responses", "response"}:
        return "responses"
    return "chat_completions"
