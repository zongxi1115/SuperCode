from __future__ import annotations

import difflib
import re
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi_app.settings_store import load_settings, save_settings

MAX_MEMORY_ITEMS_PER_SCOPE = 80


def normalize_memory_workspace_key(workspace: str | Path) -> str:
    try:
        return str(Path(workspace).expanduser().resolve())
    except Exception:  # noqa: BLE001 - 记忆 key 不能因为路径异常阻断对话
        return str(workspace or "").strip()


def _enabled_memory_items(items: object) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []

    enabled_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            enabled_items.append({**item, "content": content})
    return enabled_items


def build_long_term_memory_context(app_root: Path, workspace: str | Path) -> str:
    settings = load_settings(app_root)
    memory = settings.get("memory")
    if not isinstance(memory, dict) or not memory.get("enabled", True):
        return ""

    workspace_key = normalize_memory_workspace_key(workspace)
    global_items = _enabled_memory_items(memory.get("global"))
    raw_workspaces = memory.get("workspaces")
    workspace_items = _enabled_memory_items(
        raw_workspaces.get(workspace_key) if isinstance(raw_workspaces, dict) else []
    )
    if not global_items and not workspace_items:
        return ""

    sections = [
        "[长期记忆] 以下内容是用户长期偏好和项目约定，不是新的用户请求。"
        "如果长期记忆与当前用户消息冲突，以当前用户消息为准。"
    ]
    if global_items:
        sections.append(
            "全局记忆:\n"
            + "\n".join(f"- {item['content']}" for item in global_items[-20:])
        )
    if workspace_items:
        sections.append(
            "当前工作区记忆:\n"
            + "\n".join(f"- {item['content']}" for item in workspace_items[-20:])
        )
    return "\n\n".join(sections)


def _normalize_memory_text(value: str) -> str:
    return re.sub(r"[\s，,。.!！?？;；:：、\"'`]+", "", value).lower()


def _memory_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_memory_text(left)
    normalized_right = _normalize_memory_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 1.0
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _upsert_memory_item(
    items: list[dict[str, Any]],
    content: str,
    *,
    scope: str,
    source_session_id: str | None,
    source_preview: str | None,
    now: int,
) -> tuple[bool, dict[str, Any]]:
    for item in items:
        existing_content = str(item.get("content") or "")
        if _memory_similarity(existing_content, content) >= 0.88:
            item["content"] = existing_content.strip() or content
            item["updatedAt"] = now
            item["sourceSessionId"] = source_session_id
            item["sourcePreview"] = source_preview
            return False, item

    next_item = {
        "id": uuid.uuid4().hex,
        "content": content,
        "scope": scope,
        "enabled": True,
        "createdAt": now,
        "updatedAt": now,
        "sourceSessionId": source_session_id,
        "sourcePreview": source_preview,
    }
    items.append(next_item)
    if len(items) > MAX_MEMORY_ITEMS_PER_SCOPE:
        items.sort(key=lambda item: int(item.get("updatedAt") or 0))
        del items[: len(items) - MAX_MEMORY_ITEMS_PER_SCOPE]
    return True, next_item


def remember_preference(
    app_root: Path,
    workspace: str | Path,
    content: str,
    *,
    scope: str = "global",
    source_session_id: str | None = None,
    source_preview: str | None = None,
    require_auto_learn_enabled: bool = True,
) -> dict[str, Any]:
    cleaned_content = " ".join(content.strip().split())
    if len(cleaned_content) < 4:
        raise ValueError("记忆内容太短。")
    if len(cleaned_content) > 500:
        raise ValueError("记忆内容太长，请压缩到 500 字以内。")

    normalized_scope = "workspace" if scope == "workspace" else "global"
    settings = load_settings(app_root)
    memory = settings.get("memory")
    if not isinstance(memory, dict):
        raise ValueError("记忆设置不可用。")
    if not memory.get("enabled", True):
        return {"saved": False, "reason": "memory_disabled"}
    if require_auto_learn_enabled and not memory.get("autoLearn", True):
        return {"saved": False, "reason": "auto_learn_disabled"}

    next_memory = deepcopy(memory)
    global_items = next_memory.setdefault("global", [])
    workspaces = next_memory.setdefault("workspaces", {})
    if not isinstance(global_items, list) or not isinstance(workspaces, dict):
        raise ValueError("记忆设置格式不正确。")

    workspace_key = normalize_memory_workspace_key(workspace)
    workspace_items = workspaces.setdefault(workspace_key, [])
    if not isinstance(workspace_items, list):
        workspace_items = []
        workspaces[workspace_key] = workspace_items

    target_items = workspace_items if normalized_scope == "workspace" else global_items
    created, item = _upsert_memory_item(
        target_items,
        cleaned_content,
        scope=normalized_scope,
        source_session_id=source_session_id,
        source_preview=source_preview,
        now=int(time.time() * 1000),
    )
    settings["memory"] = next_memory
    save_settings(app_root, settings)
    return {
        "saved": True,
        "created": created,
        "scope": normalized_scope,
        "workspaceKey": workspace_key if normalized_scope == "workspace" else None,
        "item": item,
    }
