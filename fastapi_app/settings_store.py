from __future__ import annotations

import json
import time
import uuid
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
    "memory": {
        "enabled": True,
        "autoLearn": True,
        "global": [],
        "workspaces": {},
    },
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _normalize_memory_item(raw_item: object, scope: str) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None

    content = str(raw_item.get("content") or "").strip()
    if not content:
        return None

    now = _now_ms()
    created_at = raw_item.get("createdAt")
    updated_at = raw_item.get("updatedAt")
    return {
        "id": str(raw_item.get("id") or uuid.uuid4().hex),
        "content": content,
        "scope": "workspace" if scope == "workspace" else "global",
        "enabled": bool(raw_item.get("enabled", True)),
        "createdAt": int(created_at) if isinstance(created_at, (int, float)) else now,
        "updatedAt": int(updated_at) if isinstance(updated_at, (int, float)) else now,
        "sourceSessionId": (
            str(raw_item.get("sourceSessionId"))
            if raw_item.get("sourceSessionId") is not None
            else None
        ),
        "sourcePreview": (
            str(raw_item.get("sourcePreview"))
            if raw_item.get("sourcePreview") is not None
            else None
        ),
    }


def _normalize_memory_settings(raw_memory: object) -> dict[str, Any]:
    default_memory = deepcopy(DEFAULT_SETTINGS["memory"])
    if not isinstance(raw_memory, dict):
        return default_memory

    raw_global_items = raw_memory.get("global")
    global_items = [
        item
        for item in (
            _normalize_memory_item(raw_item, "global")
            for raw_item in raw_global_items
        )
        if item is not None
    ] if isinstance(raw_global_items, list) else []

    workspaces: dict[str, list[dict[str, Any]]] = {}
    raw_workspaces = raw_memory.get("workspaces")
    if isinstance(raw_workspaces, dict):
        for raw_workspace, raw_items in raw_workspaces.items():
            workspace = str(raw_workspace or "").strip()
            if not workspace or not isinstance(raw_items, list):
                continue
            items = [
                item
                for item in (
                    _normalize_memory_item(raw_item, "workspace")
                    for raw_item in raw_items
                )
                if item is not None
            ]
            if items:
                workspaces[workspace] = items

    return {
        **default_memory,
        "enabled": bool(raw_memory.get("enabled", default_memory["enabled"])),
        "autoLearn": bool(raw_memory.get("autoLearn", default_memory["autoLearn"])),
        "global": global_items,
        "workspaces": workspaces,
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
    merged["memory"] = _normalize_memory_settings(payload.get("memory"))
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
    path = settings_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return merged
