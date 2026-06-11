from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi_app.secure_config_store import get_secure_config_store

CONFIG_DIRECTORY_NAME = ".supercode"
SETTINGS_FILE_NAME = "settings.json"
SENSITIVE_SETTING_KEYS = ("embedding", "imageGeneration")

DEFAULT_SETTINGS: dict[str, Any] = {
    "autoApprove": False,
    "thinkingRendering": "text",
    "finalAnswerRendering": "markdown",
    "bodyFontFamily": 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    "bodyFontSize": 14,
    "bodyLineHeight": 22,
    "embedding": {
        "enabled": False,
        "baseUrl": "",
        "apiKey": "",
        "model": "",
    },
    "imageGeneration": {
        "enabled": False,
        "baseUrl": "",
        "apiKey": "",
        "model": "",
        "size": "1024x1024",
        "quality": "auto",
    },
}


def _merge_settings(payload: dict[str, Any]) -> dict[str, Any]:
    merged = {**deepcopy(DEFAULT_SETTINGS), **payload}
    if merged.get("finalAnswerRendering") not in {"markdown", "html"}:
        merged["finalAnswerRendering"] = DEFAULT_SETTINGS["finalAnswerRendering"]
    default_embedding = DEFAULT_SETTINGS["embedding"]
    raw_embedding = payload.get("embedding")
    if isinstance(default_embedding, dict) and isinstance(raw_embedding, dict):
        merged["embedding"] = {**default_embedding, **raw_embedding}
    elif isinstance(default_embedding, dict):
        merged["embedding"] = {**default_embedding}
    default_image_generation = DEFAULT_SETTINGS["imageGeneration"]
    raw_image_generation = payload.get("imageGeneration")
    if isinstance(default_image_generation, dict) and isinstance(raw_image_generation, dict):
        merged["imageGeneration"] = {**default_image_generation, **raw_image_generation}
    elif isinstance(default_image_generation, dict):
        merged["imageGeneration"] = {**default_image_generation}
    return merged


def settings_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / SETTINGS_FILE_NAME


def _read_settings_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_sensitive_setting(key: str, value: dict[str, Any] | None) -> dict[str, Any]:
    default_value = DEFAULT_SETTINGS[key]
    if isinstance(default_value, dict) and isinstance(value, dict):
        return {**default_value, **value}
    if isinstance(default_value, dict):
        return {**default_value}
    return {}


def _migrate_sensitive_settings_from_json(
    path: Path,
    payload: dict[str, Any],
    secure_store: Any,
) -> dict[str, Any]:
    if not path.exists() or not payload:
        return payload

    cleaned_payload = {**payload}
    changed = False
    for key in SENSITIVE_SETTING_KEYS:
        raw_value = payload.get(key)
        if isinstance(raw_value, dict) and not secure_store.has_setting(key):
            secure_store.save_setting(key, _normalize_sensitive_setting(key, raw_value))
        if key in cleaned_payload and secure_store.has_setting(key):
            cleaned_payload.pop(key, None)
            changed = True

    if changed:
        path.write_text(
            json.dumps(cleaned_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cleaned_payload


def load_settings(root: Path) -> dict[str, Any]:
    """加载设置；首次启动时把敏感配置从 JSON 迁移到加密数据库。"""
    path = settings_store_path(root)
    secure_store = get_secure_config_store(root)
    payload = _migrate_sensitive_settings_from_json(
        path,
        _read_settings_payload(path),
        secure_store,
    )
    base_settings = _merge_settings(payload)
    for key in SENSITIVE_SETTING_KEYS:
        base_settings[key] = _normalize_sensitive_setting(
            key,
            secure_store.load_setting(key, DEFAULT_SETTINGS[key]),
        )
    return base_settings


def save_settings(root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    """保存设置，敏感配置存入数据库"""
    merged = _merge_settings(settings)

    # 提取敏感配置存入数据库
    embedding_config = merged.pop("embedding", DEFAULT_SETTINGS["embedding"])
    image_gen_config = merged.pop("imageGeneration", DEFAULT_SETTINGS["imageGeneration"])
    merged.pop("memory", None)

    secure_store = get_secure_config_store(root)
    secure_store.save_setting("embedding", embedding_config)
    secure_store.save_setting("imageGeneration", image_gen_config)

    # 保存非敏感配置到文件
    path = settings_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 返回完整配置
    merged["embedding"] = embedding_config
    merged["imageGeneration"] = image_gen_config
    return merged
