from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_DIRECTORY_NAME = ".supercode"
SETTINGS_FILE_NAME = "settings.json"

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
    return merged


def settings_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / SETTINGS_FILE_NAME


def load_settings(root: Path) -> dict[str, Any]:
    path = settings_store_path(root)
    if not path.exists():
        return deepcopy(DEFAULT_SETTINGS)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULT_SETTINGS)

    if not isinstance(payload, dict):
        return deepcopy(DEFAULT_SETTINGS)

    return _merge_settings(payload)


def save_settings(root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    merged = _merge_settings(settings)
    merged.pop("memory", None)
    path = settings_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged
