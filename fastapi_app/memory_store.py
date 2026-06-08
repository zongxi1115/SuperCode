from __future__ import annotations

import difflib
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi_app.session_store import MemoryItemRecord
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


def load_memory_settings(app_root: Path) -> dict[str, Any]:
    from fastapi_app.main import _session_store

    payload = _session_store.load_memory_settings()
    return {
        "enabled": True,
        "autoLearn": True,
        "global": [],
        "workspaces": {},
        **payload,
    }


def save_memory_settings(
    app_root: Path,
    *,
    enabled: bool,
    auto_learn: bool,
    global_items: list[dict[str, Any]],
    workspace_items: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    from fastapi_app.main import _session_store

    items: list[MemoryItemRecord] = []
    for raw_item in global_items:
        item = _payload_to_memory_item(raw_item, scope="global", workspace_key=None)
        if item is not None:
            items.append(item)
    for workspace_key, raw_items in workspace_items.items():
        normalized_workspace_key = str(workspace_key or "").strip()
        if not normalized_workspace_key:
            continue
        for raw_item in raw_items:
            item = _payload_to_memory_item(
                raw_item,
                scope="workspace",
                workspace_key=normalized_workspace_key,
            )
            if item is not None:
                items.append(item)
    _session_store.save_memory_settings(
        enabled=enabled,
        auto_learn=auto_learn,
        items=items,
    )
    return load_memory_settings(app_root)


def build_long_term_memory_context(app_root: Path, workspace: str | Path) -> str:
    memory = load_memory_settings(app_root)
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


def _payload_to_memory_item(
    raw_item: object,
    *,
    scope: str,
    workspace_key: str | None,
) -> MemoryItemRecord | None:
    if not isinstance(raw_item, dict):
        return None
    content = str(raw_item.get("content") or "").strip()
    if not content:
        return None
    now = int(time.time() * 1000)
    created_at = raw_item.get("createdAt")
    updated_at = raw_item.get("updatedAt")
    return MemoryItemRecord(
        id=str(raw_item.get("id") or uuid.uuid4().hex),
        scope="workspace" if scope == "workspace" else "global",
        workspace_key=workspace_key,
        content=content,
        enabled=bool(raw_item.get("enabled", True)),
        created_at=int(created_at) if isinstance(created_at, (int, float)) else now,
        updated_at=int(updated_at) if isinstance(updated_at, (int, float)) else now,
        source_session_id=(
            str(raw_item.get("sourceSessionId"))
            if raw_item.get("sourceSessionId") is not None
            else None
        ),
        source_preview=(
            str(raw_item.get("sourcePreview"))
            if raw_item.get("sourcePreview") is not None
            else None
        ),
    )


def _upsert_memory_item(
    items: list[MemoryItemRecord],
    content: str,
    *,
    scope: str,
    workspace_key: str | None,
    source_session_id: str | None,
    source_preview: str | None,
    now: int,
) -> tuple[bool, MemoryItemRecord]:
    for item in items:
        existing_content = item.content
        if _memory_similarity(existing_content, content) >= 0.88:
            updated_item = MemoryItemRecord(
                id=item.id,
                scope=item.scope,
                workspace_key=item.workspace_key,
                content=existing_content.strip() or content,
                enabled=item.enabled,
                created_at=item.created_at,
                updated_at=now,
                source_session_id=source_session_id,
                source_preview=source_preview,
            )
            index = items.index(item)
            items[index] = updated_item
            return False, updated_item

    next_item = MemoryItemRecord(
        id=uuid.uuid4().hex,
        scope=scope,
        workspace_key=workspace_key,
        content=content,
        enabled=True,
        created_at=now,
        updated_at=now,
        source_session_id=source_session_id,
        source_preview=source_preview,
    )
    items.append(next_item)
    if len(items) > MAX_MEMORY_ITEMS_PER_SCOPE:
        items.sort(key=lambda item: item.updated_at)
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
    memory = load_memory_settings(app_root)
    if not isinstance(memory, dict):
        raise ValueError("记忆设置不可用。")
    if not memory.get("enabled", True):
        return {"saved": False, "reason": "memory_disabled"}
    if require_auto_learn_enabled and not memory.get("autoLearn", True):
        return {"saved": False, "reason": "auto_learn_disabled"}

    global_items = [
        _payload_to_memory_item(item, scope="global", workspace_key=None)
        for item in memory.get("global", [])
        if _payload_to_memory_item(item, scope="global", workspace_key=None) is not None
    ]
    workspace_key = normalize_memory_workspace_key(workspace)
    workspace_payloads = memory.get("workspaces", {})
    raw_workspace_items = workspace_payloads.get(workspace_key, []) if isinstance(workspace_payloads, dict) else []
    workspace_items = [
        _payload_to_memory_item(item, scope="workspace", workspace_key=workspace_key)
        for item in raw_workspace_items
        if _payload_to_memory_item(item, scope="workspace", workspace_key=workspace_key) is not None
    ]

    target_items = workspace_items if normalized_scope == "workspace" else global_items
    created, item = _upsert_memory_item(
        target_items,
        cleaned_content,
        scope=normalized_scope,
        workspace_key=workspace_key if normalized_scope == "workspace" else None,
        source_session_id=source_session_id,
        source_preview=source_preview,
        now=int(time.time() * 1000),
    )

    next_workspace_payloads = dict(workspace_payloads) if isinstance(workspace_payloads, dict) else {}
    next_workspace_payloads[workspace_key] = [item.to_payload() for item in workspace_items]
    save_memory_settings(
        app_root,
        enabled=bool(memory.get("enabled", True)),
        auto_learn=bool(memory.get("autoLearn", True)),
        global_items=[item.to_payload() for item in global_items],
        workspace_items=next_workspace_payloads,
    )
    return {
        "saved": True,
        "created": created,
        "scope": normalized_scope,
        "workspaceKey": workspace_key if normalized_scope == "workspace" else None,
        "item": item.to_payload(),
    }
