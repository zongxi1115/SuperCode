from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIRECTORY_NAME = ".supercode"
SETTINGS_FILE_NAME = "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "autoApprove": False,
    "thinkingRendering": "text",
}


def settings_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / SETTINGS_FILE_NAME


def load_settings(root: Path) -> dict[str, Any]:
    path = settings_store_path(root)
    if not path.exists():
        return {**DEFAULT_SETTINGS}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**DEFAULT_SETTINGS}

    if not isinstance(payload, dict):
        return {**DEFAULT_SETTINGS}

    return {**DEFAULT_SETTINGS, **payload}


def save_settings(root: Path, settings: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_SETTINGS, **settings}
    path = settings_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged
