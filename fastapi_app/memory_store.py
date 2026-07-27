from __future__ import annotations

import difflib
import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_MEMORY_ITEMS_PER_SCOPE = 80
MEMORY_MIGRATION_VERSION = "memory-from-settings-json-v1"


@dataclass(slots=True)
class MemoryItemRecord:
    id: str
    scope: str
    workspace_key: str | None
    content: str
    enabled: bool
    created_at: int
    updated_at: int
    source_session_id: str | None = None
    source_preview: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "scope": self.scope,
            "enabled": self.enabled,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "sourceSessionId": self.source_session_id,
            "sourcePreview": self.source_preview,
        }


class SQLiteMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._lock, self._connect() as connection:
            self._initialize_schema(connection)
            self._migrate_settings_json(connection)

    def load(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            config_row = connection.execute(
                "SELECT enabled, auto_learn FROM memory_config WHERE id = 1"
            ).fetchone()
            enabled = bool(config_row["enabled"]) if config_row is not None else True
            auto_learn = bool(config_row["auto_learn"]) if config_row is not None else True
            rows = connection.execute(
                """
                SELECT id, scope, workspace_key, content, enabled, created_at, updated_at,
                       source_session_id, source_preview
                FROM memory_items
                ORDER BY updated_at ASC, created_at ASC, id ASC
                """
            ).fetchall()

        global_items: list[dict[str, Any]] = []
        workspaces: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            record = self._row_to_record(row)
            if record.scope == "workspace" and record.workspace_key:
                workspaces.setdefault(record.workspace_key, []).append(record.to_payload())
            else:
                global_items.append(record.to_payload())
        return {
            "enabled": enabled,
            "autoLearn": auto_learn,
            "global": global_items,
            "workspaces": workspaces,
        }

    def save(
        self,
        *,
        enabled: bool,
        auto_learn: bool,
        items: list[MemoryItemRecord] | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
            self._save(connection, enabled=enabled, auto_learn=auto_learn, items=items)

    def _save(
        self,
        connection: sqlite3.Connection,
        *,
        enabled: bool,
        auto_learn: bool,
        items: list[MemoryItemRecord] | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_config (id, enabled, auto_learn)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                enabled = excluded.enabled,
                auto_learn = excluded.auto_learn
            """,
            (1 if enabled else 0, 1 if auto_learn else 0),
        )
        if items is None:
            return
        connection.execute("DELETE FROM memory_items")
        if items:
            connection.executemany(
                """
                INSERT INTO memory_items (
                    id, scope, workspace_key, content, enabled, created_at, updated_at,
                    source_session_id, source_preview
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.scope,
                        item.workspace_key,
                        item.content,
                        1 if item.enabled else 0,
                        item.created_at,
                        item.updated_at,
                        item.source_session_id,
                        item.source_preview,
                    )
                    for item in items
                ],
            )

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                key TEXT PRIMARY KEY,
                applied_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL DEFAULT 1,
                auto_learn INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                workspace_key TEXT,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source_session_id TEXT,
                source_preview TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_items_scope_workspace
            ON memory_items(scope, workspace_key, updated_at)
            """
        )

    def _migrate_settings_json(self, connection: sqlite3.Connection) -> None:
        migrated = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE key = ?",
            (MEMORY_MIGRATION_VERSION,),
        ).fetchone()
        if migrated is not None:
            return

        settings_path = self.db_path.parent / "settings.json"
        if not settings_path.exists():
            return
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._mark_migrated(connection)
            return
        raw_memory = payload.get("memory") if isinstance(payload, dict) else None
        if not isinstance(raw_memory, dict):
            self._mark_migrated(connection)
            return

        items: list[MemoryItemRecord] = []
        raw_global = raw_memory.get("global")
        if isinstance(raw_global, list):
            for raw_item in raw_global:
                item = self._legacy_item(raw_item, scope="global", workspace_key=None)
                if item is not None:
                    items.append(item)
        raw_workspaces = raw_memory.get("workspaces")
        if isinstance(raw_workspaces, dict):
            for workspace_key, raw_items in raw_workspaces.items():
                if not isinstance(raw_items, list):
                    continue
                normalized_key = str(workspace_key or "").strip() or None
                for raw_item in raw_items:
                    item = self._legacy_item(
                        raw_item,
                        scope="workspace",
                        workspace_key=normalized_key,
                    )
                    if item is not None:
                        items.append(item)

        self._save(
            connection,
            enabled=bool(raw_memory.get("enabled", True)),
            auto_learn=bool(raw_memory.get("autoLearn", True)),
            items=items,
        )
        cleaned_payload = dict(payload)
        cleaned_payload.pop("memory", None)
        settings_path.write_text(
            json.dumps(cleaned_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mark_migrated(connection)

    def _legacy_item(
        self,
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
        created_at = self._optional_int(raw_item.get("createdAt"))
        updated_at = self._optional_int(raw_item.get("updatedAt"))
        timestamp = updated_at or created_at or 1
        return MemoryItemRecord(
            id=str(raw_item.get("id") or uuid.uuid4().hex),
            scope=scope,
            workspace_key=workspace_key,
            content=content,
            enabled=bool(raw_item.get("enabled", True)),
            created_at=created_at or timestamp,
            updated_at=updated_at or timestamp,
            source_session_id=str(raw_item.get("sourceSessionId") or "") or None,
            source_preview=str(raw_item.get("sourcePreview") or "") or None,
        )

    def _mark_migrated(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO schema_migrations (key, applied_at)
            VALUES (?, strftime('%s','now') * 1000)
            ON CONFLICT(key) DO NOTHING
            """,
            (MEMORY_MIGRATION_VERSION,),
        )

    def _row_to_record(self, row: sqlite3.Row) -> MemoryItemRecord:
        return MemoryItemRecord(
            id=str(row["id"]),
            scope=str(row["scope"]),
            workspace_key=row["workspace_key"],
            content=str(row["content"]),
            enabled=bool(row["enabled"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            source_session_id=row["source_session_id"],
            source_preview=row["source_preview"],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


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


def load_memory_settings(memory_store: SQLiteMemoryStore) -> dict[str, Any]:
    payload = memory_store.load()
    return {
        "enabled": True,
        "autoLearn": True,
        "global": [],
        "workspaces": {},
        **payload,
    }


def save_memory_settings(
    memory_store: SQLiteMemoryStore,
    *,
    enabled: bool,
    auto_learn: bool,
    global_items: list[dict[str, Any]],
    workspace_items: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
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
    memory_store.save(
        enabled=enabled,
        auto_learn=auto_learn,
        items=items,
    )
    return load_memory_settings(memory_store)


def build_long_term_memory_context(
    memory_store: SQLiteMemoryStore,
    workspace: str | Path,
) -> str:
    memory = load_memory_settings(memory_store)
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
    memory_store: SQLiteMemoryStore,
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
    memory = load_memory_settings(memory_store)
    if not memory.get("enabled", True):
        return {"saved": False, "reason": "memory_disabled"}
    if require_auto_learn_enabled and not memory.get("autoLearn", True):
        return {"saved": False, "reason": "auto_learn_disabled"}

    global_items: list[MemoryItemRecord] = []
    for raw_item in memory.get("global", []):
        item = _payload_to_memory_item(raw_item, scope="global", workspace_key=None)
        if item is not None:
            global_items.append(item)
    workspace_key = normalize_memory_workspace_key(workspace)
    workspace_payloads = memory.get("workspaces", {})
    raw_workspace_items = workspace_payloads.get(workspace_key, []) if isinstance(workspace_payloads, dict) else []
    workspace_items: list[MemoryItemRecord] = []
    for raw_item in raw_workspace_items:
        item = _payload_to_memory_item(
            raw_item,
            scope="workspace",
            workspace_key=workspace_key,
        )
        if item is not None:
            workspace_items.append(item)

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
        memory_store,
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
