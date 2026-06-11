from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LEGACY_SESSIONS_TABLE = "sessions_legacy_v1"
SESSION_SCHEMA_VERSION = "session-schema-v2"
MEMORY_MIGRATION_VERSION = "memory-from-settings-json-v1"
MESSAGE_METADATA_KEYS = (
    "agentScope",
    "subagentId",
    "parentToolCallId",
    "parentAssistantId",
    "subagentTitle",
    "subagentTask",
)
TOOL_METADATA_KEYS = (
    "agentScope",
    "subagentId",
    "parentToolCallId",
    "parentAssistantId",
    "subagentTitle",
    "subagentTask",
)


@dataclass(slots=True)
class PersistedSessionState:
    session_id: str
    workspace: str
    mode: str
    model: str
    title: str
    preview: str
    message_count: int
    tool_call_count: int
    created_at: int
    updated_at: int
    reasoning_effort: str | None = None
    execution_mode: str = "local"
    base_workspace: str | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None
    agent_type: str = "coding"
    phase: str = "idle"
    route_state: dict[str, Any] = field(default_factory=dict)
    is_generating: bool = False
    startup_error: str | None = None
    env_file: str | None = None
    selected_file_path: str | None = None
    open_files: list[str] = field(default_factory=list)
    terminal_output: str = ""
    preview_url: str = ""
    history_messages: list[dict[str, Any]] = field(default_factory=list)
    history_tools: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    cumulative_token_usage: dict[str, int] = field(default_factory=dict)
    max_context_tokens: int | None = None
    plan_steps: list[dict[str, str]] = field(default_factory=list)
    plan_state: dict[str, Any] = field(default_factory=dict)
    code_changes: list[dict[str, Any]] = field(default_factory=list)
    pending_delete_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_commit_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_tag_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_user_input_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_connect_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    deploy_connections: dict[str, dict[str, Any]] = field(default_factory=dict)
    deploy_state: dict[str, Any] = field(default_factory=dict)


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


class SessionStateAdapter(ABC):
    @abstractmethod
    def save(self, state: PersistedSessionState) -> None:
        raise NotImplementedError

    @abstractmethod
    def load(self, session_id: str) -> PersistedSessionState | None:
        raise NotImplementedError

    @abstractmethod
    def list(self, *, limit: int | None = None, offset: int = 0) -> list[PersistedSessionState]:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def delete(self, session_id: str) -> None:
        raise NotImplementedError


class SQLiteSessionStateAdapter(SessionStateAdapter):
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize_database()
        self._migrate_settings_memory_if_needed()

    def save(self, state: PersistedSessionState) -> None:
        normalized_state = self._normalize_state(state)
        with self._lock, self._connect() as connection:
            self._save_session_core(connection, normalized_state)
            self._replace_session_open_files(connection, normalized_state)
            self._replace_session_usage(connection, normalized_state)
            self._replace_session_messages(connection, normalized_state)
            self._replace_session_message_parts(connection, normalized_state)
            self._replace_session_tool_calls(connection, normalized_state)
            self._replace_session_code_changes(connection, normalized_state)
            self._replace_session_plan_steps(connection, normalized_state)
            self._replace_session_artifacts(connection, normalized_state)

    def load(self, session_id: str) -> PersistedSessionState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_state(connection, row, include_large_fields=True)

    def list(self, *, limit: int | None = None, offset: int = 0) -> list[PersistedSessionState]:
        normalized_offset = max(0, int(offset))
        parameters: list[Any] = []
        query = """
            SELECT
                session_id, workspace, mode, model, reasoning_effort, execution_mode,
                base_workspace, worktree_path, worktree_branch, agent_type, phase,
                title, preview, message_count, tool_call_count, created_at, updated_at
            FROM sessions
            ORDER BY updated_at DESC
        """
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            parameters.extend([max(0, int(limit)), normalized_offset])
        elif normalized_offset:
            query += " LIMIT -1 OFFSET ?"
            parameters.append(normalized_offset)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [self._row_to_list_state(row) for row in rows]

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM sessions").fetchone()
            return int(row["total"] if row is not None else 0)

    def delete(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT workspace FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        if row is not None:
            shutil.rmtree(
                self._session_artifacts_dir(str(row["workspace"]), session_id),
                ignore_errors=True,
            )

    def load_memory_settings(self) -> dict[str, Any]:
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
            record = self._row_to_memory_item(row)
            payload = record.to_payload()
            if record.scope == "workspace":
                workspace_key = str(record.workspace_key or "").strip()
                if workspace_key:
                    workspaces.setdefault(workspace_key, []).append(payload)
            else:
                global_items.append(payload)
        return {
            "enabled": enabled,
            "autoLearn": auto_learn,
            "global": global_items,
            "workspaces": workspaces,
        }

    def save_memory_settings(
        self,
        *,
        enabled: bool,
        auto_learn: bool,
        items: list[MemoryItemRecord] | None = None,
    ) -> None:
        with self._lock, self._connect() as connection:
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
            if not items:
                return
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

    def _initialize_database(self) -> None:
        with self._lock, self._connect() as connection:
            self._ensure_meta_schema(connection)
            if not self._has_schema_migration(connection, SESSION_SCHEMA_VERSION):
                self._migrate_sessions_schema(connection)
                self._mark_schema_migration(connection, SESSION_SCHEMA_VERSION)
            else:
                self._ensure_runtime_schema(connection)

    def _ensure_meta_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                key TEXT PRIMARY KEY,
                applied_at INTEGER NOT NULL
            )
            """
        )

    def _ensure_runtime_schema(self, connection: sqlite3.Connection) -> None:
        self._create_runtime_tables(connection)
        self._ensure_session_message_columns(connection)
        self._ensure_session_tool_call_columns(connection)
        self._ensure_indexes(connection)

    def _migrate_sessions_schema(self, connection: sqlite3.Connection) -> None:
        table_exists = self._table_exists(connection, "sessions")
        legacy_exists = self._table_exists(connection, LEGACY_SESSIONS_TABLE)
        legacy_rows: list[sqlite3.Row] = []
        if legacy_exists:
            legacy_rows = connection.execute(
                f"SELECT * FROM {LEGACY_SESSIONS_TABLE} ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
            self._drop_session_tables(connection)
        elif table_exists:
            existing_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "route_state" in existing_columns or "history_messages" in existing_columns:
                self._drop_session_tables(connection, keep_legacy=True)
                connection.execute(f"ALTER TABLE sessions RENAME TO {LEGACY_SESSIONS_TABLE}")
                legacy_rows = connection.execute(
                    f"SELECT * FROM {LEGACY_SESSIONS_TABLE} ORDER BY updated_at DESC, created_at DESC"
                ).fetchall()
            else:
                self._drop_session_tables(connection)
        self._ensure_runtime_schema(connection)
        if legacy_rows:
            for row in legacy_rows:
                self.save(self._legacy_row_to_state(row))
            connection.execute(f"DROP TABLE IF EXISTS {LEGACY_SESSIONS_TABLE}")

    def _create_runtime_tables(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                mode TEXT NOT NULL,
                model TEXT NOT NULL,
                reasoning_effort TEXT,
                execution_mode TEXT NOT NULL DEFAULT 'local',
                base_workspace TEXT,
                worktree_path TEXT,
                worktree_branch TEXT,
                agent_type TEXT NOT NULL DEFAULT 'coding',
                phase TEXT NOT NULL DEFAULT 'idle',
                title TEXT NOT NULL,
                preview TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                tool_call_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                is_generating INTEGER NOT NULL DEFAULT 0,
                startup_error TEXT,
                env_file TEXT,
                selected_file_path TEXT,
                open_files_json TEXT NOT NULL DEFAULT '[]',
                terminal_preview TEXT NOT NULL DEFAULT '',
                preview_url TEXT NOT NULL DEFAULT '',
                route_state_json TEXT NOT NULL DEFAULT '{}',
                plan_state_json TEXT NOT NULL DEFAULT '{}',
                pending_delete_confirmations_json TEXT NOT NULL DEFAULT '{}',
                pending_commit_confirmations_json TEXT NOT NULL DEFAULT '{}',
                pending_tag_confirmations_json TEXT NOT NULL DEFAULT '{}',
                pending_user_input_requests_json TEXT NOT NULL DEFAULT '{}',
                pending_connect_requests_json TEXT NOT NULL DEFAULT '{}',
                deploy_connections_json TEXT NOT NULL DEFAULT '{}',
                deploy_state_json TEXT NOT NULL DEFAULT '{}',
                max_context_tokens INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_open_files (
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                path TEXT NOT NULL,
                PRIMARY KEY (session_id, position),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_usage (
                session_id TEXT NOT NULL,
                usage_scope TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                cached_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, usage_scope),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                thought_text TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                turn_index INTEGER,
                thinking_time REAL,
                message_index INTEGER NOT NULL,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_message_parts (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                part_index INTEGER NOT NULL,
                part_type TEXT NOT NULL,
                text_value TEXT,
                tool_call_id TEXT,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id, message_id) REFERENCES session_messages(session_id, id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tool_calls (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                assistant_id TEXT,
                tool_name TEXT NOT NULL,
                state TEXT NOT NULL,
                success INTEGER,
                arguments_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT 'null',
                error_message TEXT,
                summary TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                approval_json TEXT,
                input_request_json TEXT,
                started_at INTEGER NOT NULL,
                finished_at INTEGER NOT NULL,
                turn_index INTEGER,
                step_index INTEGER,
                tool_index INTEGER NOT NULL,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_code_changes (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                tool_call_id TEXT,
                assistant_id TEXT,
                path TEXT NOT NULL,
                absolute_path TEXT,
                action TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'agent',
                lines_added INTEGER NOT NULL DEFAULT 0,
                lines_deleted INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                diff_preview TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL,
                turn_index INTEGER,
                step_index INTEGER,
                change_index INTEGER NOT NULL,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_plan_steps (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_artifacts (
                session_id TEXT NOT NULL,
                id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
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

    def _ensure_session_message_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(session_messages)").fetchall()
        }
        if "thinking_time" not in existing_columns:
            connection.execute("ALTER TABLE session_messages ADD COLUMN thinking_time REAL")
        if "metadata_json" not in existing_columns:
            connection.execute("ALTER TABLE session_messages ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def _ensure_session_tool_call_columns(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(session_tool_calls)").fetchall()
        }
        if "metadata_json" not in existing_columns:
            connection.execute("ALTER TABLE session_tool_calls ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def _ensure_indexes(self, connection: sqlite3.Connection) -> None:
        statements = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_session_messages_order ON session_messages(session_id, message_index)",
            "CREATE INDEX IF NOT EXISTS idx_session_message_parts_order ON session_message_parts(session_id, message_id, part_index)",
            "CREATE INDEX IF NOT EXISTS idx_session_tool_calls_order ON session_tool_calls(session_id, tool_index)",
            "CREATE INDEX IF NOT EXISTS idx_session_code_changes_order ON session_code_changes(session_id, change_index)",
            "CREATE INDEX IF NOT EXISTS idx_session_plan_steps_order ON session_plan_steps(session_id, position)",
            "CREATE INDEX IF NOT EXISTS idx_session_artifacts_kind ON session_artifacts(session_id, kind)",
            "CREATE INDEX IF NOT EXISTS idx_memory_items_scope_workspace ON memory_items(scope, workspace_key, updated_at)",
        ]
        for statement in statements:
            connection.execute(statement)

    def _migrate_settings_memory_if_needed(self) -> None:
        settings_path = self.db_path.parent / "settings.json"
        if not settings_path.exists():
            return
        with self._lock, self._connect() as connection:
            if self._has_schema_migration(connection, MEMORY_MIGRATION_VERSION):
                return
            try:
                payload = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._mark_schema_migration(connection, MEMORY_MIGRATION_VERSION)
                return
            if not isinstance(payload, dict):
                self._mark_schema_migration(connection, MEMORY_MIGRATION_VERSION)
                return
            raw_memory = payload.get("memory")
            if not isinstance(raw_memory, dict):
                self._mark_schema_migration(connection, MEMORY_MIGRATION_VERSION)
                return

            enabled = bool(raw_memory.get("enabled", True))
            auto_learn = bool(raw_memory.get("autoLearn", True))
            items: list[MemoryItemRecord] = []
            raw_global = raw_memory.get("global")
            if isinstance(raw_global, list):
                for raw_item in raw_global:
                    item = self._raw_memory_item_to_record(
                        raw_item,
                        scope="global",
                        workspace_key=None,
                    )
                    if item is not None:
                        items.append(item)
            raw_workspaces = raw_memory.get("workspaces")
            if isinstance(raw_workspaces, dict):
                for workspace_key, raw_items in raw_workspaces.items():
                    if not isinstance(raw_items, list):
                        continue
                    for raw_item in raw_items:
                        item = self._raw_memory_item_to_record(
                            raw_item,
                            scope="workspace",
                            workspace_key=str(workspace_key or "").strip() or None,
                        )
                        if item is not None:
                            items.append(item)
            self.save_memory_settings(
                enabled=enabled,
                auto_learn=auto_learn,
                items=items,
            )
            cleaned_payload = {**payload}
            cleaned_payload.pop("memory", None)
            try:
                settings_path.write_text(
                    json.dumps(cleaned_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
            self._mark_schema_migration(connection, MEMORY_MIGRATION_VERSION)

    def _save_session_core(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute(
            """
            INSERT INTO sessions (
                session_id, workspace, mode, model, reasoning_effort, execution_mode,
                base_workspace, worktree_path, worktree_branch, agent_type, phase,
                title, preview, message_count, tool_call_count, created_at, updated_at,
                is_generating, startup_error, env_file, selected_file_path, open_files_json,
                terminal_preview, preview_url, route_state_json, plan_state_json,
                pending_delete_confirmations_json, pending_commit_confirmations_json,
                pending_tag_confirmations_json, pending_user_input_requests_json,
                pending_connect_requests_json, deploy_connections_json, deploy_state_json,
                max_context_tokens
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                workspace = excluded.workspace,
                mode = excluded.mode,
                model = excluded.model,
                reasoning_effort = excluded.reasoning_effort,
                execution_mode = excluded.execution_mode,
                base_workspace = excluded.base_workspace,
                worktree_path = excluded.worktree_path,
                worktree_branch = excluded.worktree_branch,
                agent_type = excluded.agent_type,
                phase = excluded.phase,
                title = excluded.title,
                preview = excluded.preview,
                message_count = excluded.message_count,
                tool_call_count = excluded.tool_call_count,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                is_generating = excluded.is_generating,
                startup_error = excluded.startup_error,
                env_file = excluded.env_file,
                selected_file_path = excluded.selected_file_path,
                open_files_json = excluded.open_files_json,
                terminal_preview = excluded.terminal_preview,
                preview_url = excluded.preview_url,
                route_state_json = excluded.route_state_json,
                plan_state_json = excluded.plan_state_json,
                pending_delete_confirmations_json = excluded.pending_delete_confirmations_json,
                pending_commit_confirmations_json = excluded.pending_commit_confirmations_json,
                pending_tag_confirmations_json = excluded.pending_tag_confirmations_json,
                pending_user_input_requests_json = excluded.pending_user_input_requests_json,
                pending_connect_requests_json = excluded.pending_connect_requests_json,
                deploy_connections_json = excluded.deploy_connections_json,
                deploy_state_json = excluded.deploy_state_json,
                max_context_tokens = excluded.max_context_tokens
            """,
            (
                state.session_id,
                state.workspace,
                state.mode,
                state.model,
                state.reasoning_effort,
                state.execution_mode,
                state.base_workspace,
                state.worktree_path,
                state.worktree_branch,
                state.agent_type,
                state.phase,
                state.title,
                state.preview,
                state.message_count,
                state.tool_call_count,
                state.created_at,
                state.updated_at,
                1 if state.is_generating else 0,
                state.startup_error,
                state.env_file,
                state.selected_file_path,
                self._to_json(state.open_files),
                state.terminal_output[-4000:],
                state.preview_url,
                self._to_json(state.route_state),
                self._to_json(state.plan_state),
                self._to_json(state.pending_delete_confirmations),
                self._to_json(state.pending_commit_confirmations),
                self._to_json(state.pending_tag_confirmations),
                self._to_json(state.pending_user_input_requests),
                self._to_json(state.pending_connect_requests),
                self._to_json(state.deploy_connections),
                self._to_json(state.deploy_state),
                state.max_context_tokens,
            ),
        )

    def _replace_session_open_files(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_open_files WHERE session_id = ?", (state.session_id,))
        rows = [
            (state.session_id, index, path)
            for index, path in enumerate(state.open_files, start=1)
            if str(path).strip()
        ]
        if rows:
            connection.executemany(
                """
                INSERT INTO session_open_files (session_id, position, path)
                VALUES (?, ?, ?)
                """,
                rows,
            )

    def _replace_session_usage(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_usage WHERE session_id = ?", (state.session_id,))
        payloads = [
            ("current", state.token_usage),
            ("cumulative", state.cumulative_token_usage),
        ]
        connection.executemany(
            """
            INSERT INTO session_usage (
                session_id, usage_scope, input_tokens, output_tokens, reasoning_tokens,
                cached_input_tokens, total_tokens
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    state.session_id,
                    usage_scope,
                    int((payload or {}).get("inputTokens") or 0),
                    int((payload or {}).get("outputTokens") or 0),
                    int((payload or {}).get("reasoningTokens") or 0),
                    int((payload or {}).get("cachedInputTokens") or 0),
                    int((payload or {}).get("totalTokens") or 0),
                )
                for usage_scope, payload in payloads
            ],
        )

    def _replace_session_messages(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_messages WHERE session_id = ?", (state.session_id,))
        rows: list[tuple[Any, ...]] = []
        for index, message in enumerate(state.history_messages, start=1):
            message_id = str(message.get("id") or f"{state.session_id}-message-{index}")
            rows.append(
                (
                    message_id,
                    state.session_id,
                    str(message.get("role") or ""),
                    str(message.get("content") or ""),
                    self._extract_message_thoughts(message),
                    self._to_json(self._metadata_payload(message, MESSAGE_METADATA_KEYS)),
                    self._coerce_optional_int(message.get("timestamp")) or state.updated_at,
                    self._coerce_optional_int(message.get("turnIndex", message.get("turn_index"))),
                    self._coerce_optional_float(message.get("thinkingTime", message.get("thinking_time"))),
                    index,
                )
            )
        if rows:
            connection.executemany(
                """
                INSERT INTO session_messages (
                    id, session_id, role, content, thought_text, metadata_json, created_at, turn_index,
                    thinking_time, message_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _replace_session_message_parts(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_message_parts WHERE session_id = ?", (state.session_id,))
        rows: list[tuple[Any, ...]] = []
        for message_index, message in enumerate(state.history_messages, start=1):
            message_id = str(message.get("id") or f"{state.session_id}-message-{message_index}")
            parts = self._message_parts_for_storage(message)
            for part_index, part in enumerate(parts, start=1):
                part_type = str(part.get("type") or "")
                stored_part_type = part_type
                text_value = str(part.get("text") or "") if part_type in {"text", "thinking"} else None
                if part_type == "data":
                    stored_part_type = str(part.get("dataType") or "")
                    text_value = self._to_json(part.get("data"))
                rows.append(
                    (
                        f"{message_id}-part-{part_index}",
                        state.session_id,
                        message_id,
                        part_index,
                        stored_part_type,
                        text_value,
                        self._extract_tool_call_id(part),
                    )
                )
        if rows:
            connection.executemany(
                """
                INSERT INTO session_message_parts (
                    id, session_id, message_id, part_index, part_type, text_value, tool_call_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _replace_session_tool_calls(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_tool_calls WHERE session_id = ?", (state.session_id,))
        rows: list[tuple[Any, ...]] = []
        for index, tool in enumerate(state.history_tools, start=1):
            rows.append(
                (
                    str(tool.get("id") or f"{state.session_id}-tool-{index}"),
                    state.session_id,
                    str(tool.get("assistantId", tool.get("assistant_id")) or "") or None,
                    str(tool.get("name") or ""),
                    str(tool.get("state") or ""),
                    self._coerce_optional_bool(tool.get("success")),
                    self._to_json(tool.get("arguments") if isinstance(tool.get("arguments"), dict) else {}),
                    self._to_json(tool.get("output")),
                    str(tool.get("errorMessage", tool.get("error_message")) or "") or None,
                    self._tool_summary(tool),
                    self._to_json(self._metadata_payload(tool, TOOL_METADATA_KEYS)),
                    self._to_json(tool.get("approval")) if tool.get("approval") is not None else None,
                    self._to_json(tool.get("inputRequest")) if tool.get("inputRequest") is not None else None,
                    self._coerce_optional_int(tool.get("startedAt", tool.get("started_at"))) or state.updated_at,
                    self._coerce_optional_int(tool.get("finishedAt", tool.get("finished_at"))) or state.updated_at,
                    self._coerce_optional_int(tool.get("turnIndex", tool.get("turn_index"))),
                    self._coerce_optional_int(tool.get("stepIndex", tool.get("step_index"))),
                    index,
                )
            )
        if rows:
            connection.executemany(
                """
                INSERT INTO session_tool_calls (
                    id, session_id, assistant_id, tool_name, state, success, arguments_json, output_json,
                    error_message, summary, metadata_json, approval_json, input_request_json,
                    started_at, finished_at, turn_index, step_index, tool_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _replace_session_code_changes(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_code_changes WHERE session_id = ?", (state.session_id,))
        rows: list[tuple[Any, ...]] = []
        for index, change in enumerate(state.code_changes, start=1):
            rows.append(
                (
                    str(change.get("id") or f"{state.session_id}-change-{index}"),
                    state.session_id,
                    str(change.get("toolCallId", change.get("tool_call_id")) or "") or None,
                    str(change.get("assistantId", change.get("assistant_id")) or "") or None,
                    str(change.get("path") or ""),
                    str(change.get("absolutePath", change.get("absolute_path")) or "") or None,
                    str(change.get("action") or "modified"),
                    str(change.get("source") or "agent"),
                    int(change.get("linesAdded", change.get("lines_added")) or 0),
                    int(change.get("linesDeleted", change.get("lines_deleted")) or 0),
                    str(change.get("summary") or ""),
                    str(change.get("diffPreview", change.get("diff_preview")) or ""),
                    int(change.get("timestamp") or state.updated_at),
                    self._coerce_optional_int(change.get("turnIndex", change.get("turn_index"))),
                    self._coerce_optional_int(change.get("stepIndex", change.get("step_index"))),
                    index,
                )
            )
        if rows:
            connection.executemany(
                """
                INSERT INTO session_code_changes (
                    id, session_id, tool_call_id, assistant_id, path, absolute_path, action, source,
                    lines_added, lines_deleted, summary, diff_preview, timestamp, turn_index, step_index, change_index
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _replace_session_plan_steps(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_plan_steps WHERE session_id = ?", (state.session_id,))
        rows = [
            (
                str(step.get("id") or f"{state.session_id}-plan-step-{index}"),
                state.session_id,
                index,
                str(step.get("title") or ""),
                str(step.get("description") or ""),
                str(step.get("status") or "pending"),
                state.updated_at,
            )
            for index, step in enumerate(state.plan_steps, start=1)
            if isinstance(step, dict)
        ]
        if rows:
            connection.executemany(
                """
                INSERT INTO session_plan_steps (
                    id, session_id, position, title, description, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def _replace_session_artifacts(self, connection: sqlite3.Connection, state: PersistedSessionState) -> None:
        connection.execute("DELETE FROM session_artifacts WHERE session_id = ?", (state.session_id,))
        artifacts_dir = self._session_artifacts_dir(state.workspace, state.session_id)
        diffs_dir = artifacts_dir / "diffs"
        snapshots_dir = artifacts_dir / "snapshots"
        diffs_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        rows: list[tuple[Any, ...]] = []
        terminal_output = state.terminal_output or ""
        terminal_log_path = artifacts_dir / "terminal.log"
        if terminal_output:
            terminal_log_path.write_text(terminal_output, encoding="utf-8")
            rows.append(
                (
                    f"{state.session_id}-terminal-log",
                    state.session_id,
                    "terminal_log",
                    str(terminal_log_path),
                    len(terminal_output.encode("utf-8")),
                    state.updated_at,
                    self._to_json({"preview": terminal_output[-4000:]}),
                )
            )
        elif terminal_log_path.exists():
            terminal_log_path.unlink()

        for change in state.code_changes:
            change_id = str(change.get("id") or "").strip()
            if not change_id:
                continue
            diff_preview = str(change.get("diffPreview", change.get("diff_preview")) or "")
            full_diff = str(change.get("fullDiff", change.get("full_diff")) or diff_preview)
            if not full_diff:
                continue
            diff_path = diffs_dir / f"{change_id}.patch"
            diff_path.write_text(full_diff, encoding="utf-8")
            rows.append(
                (
                    f"{change_id}-full-diff",
                    state.session_id,
                    "full_diff",
                    str(diff_path),
                    len(full_diff.encode("utf-8")),
                    int(change.get("timestamp") or state.updated_at),
                    self._to_json(
                        {
                            "changeId": change_id,
                            "path": str(change.get("path") or ""),
                            "preview": diff_preview,
                        }
                    ),
                )
            )

        if rows:
            connection.executemany(
                """
                INSERT INTO session_artifacts (
                    id, session_id, kind, path, size, created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        else:
            shutil.rmtree(artifacts_dir, ignore_errors=True)

    def _row_to_state(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        include_large_fields: bool,
    ) -> PersistedSessionState:
        session_id = str(row["session_id"])
        if include_large_fields:
            history_tools = self._load_tool_calls(connection, session_id)
            history_messages = self._load_messages(connection, session_id, history_tools)
            thoughts = self._rebuild_thoughts_from_messages(history_messages)
            usage_map = self._load_usage_map(connection, session_id)
            terminal_output = self._load_terminal_output(connection, session_id)
            code_changes = self._load_code_changes(connection, session_id, include_large_fields=True)
            plan_steps = self._load_plan_steps(connection, session_id)
        else:
            history_tools = []
            history_messages = []
            thoughts = []
            usage_map = {}
            terminal_output = str(row["terminal_preview"] or "")
            code_changes = []
            plan_steps = []
        return PersistedSessionState(
            session_id=session_id,
            workspace=str(row["workspace"]),
            mode=str(row["mode"]),
            model=str(row["model"]),
            title=str(row["title"]),
            preview=str(row["preview"]),
            message_count=int(row["message_count"] or 0),
            tool_call_count=int(row["tool_call_count"] or 0),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            reasoning_effort=row["reasoning_effort"],
            execution_mode=str(row["execution_mode"] or "local"),
            base_workspace=row["base_workspace"],
            worktree_path=row["worktree_path"],
            worktree_branch=row["worktree_branch"],
            agent_type=str(row["agent_type"] or "coding"),
            phase=str(row["phase"] or "idle"),
            route_state=self._from_json(row["route_state_json"], {}),
            is_generating=bool(row["is_generating"]),
            startup_error=row["startup_error"],
            env_file=row["env_file"],
            selected_file_path=row["selected_file_path"],
            open_files=self._load_open_files(connection, row),
            terminal_output=terminal_output,
            preview_url=str(row["preview_url"] or ""),
            history_messages=history_messages,
            history_tools=history_tools,
            thoughts=thoughts,
            token_usage=usage_map.get("current", self._empty_usage_payload()),
            cumulative_token_usage=usage_map.get("cumulative", self._empty_usage_payload()),
            max_context_tokens=(int(row["max_context_tokens"]) if row["max_context_tokens"] is not None else None),
            plan_steps=plan_steps,
            plan_state=self._from_json(row["plan_state_json"], {}),
            code_changes=code_changes,
            pending_delete_confirmations=self._from_json(row["pending_delete_confirmations_json"], {}),
            pending_commit_confirmations=self._from_json(row["pending_commit_confirmations_json"], {}),
            pending_tag_confirmations=self._from_json(row["pending_tag_confirmations_json"], {}),
            pending_user_input_requests=self._from_json(row["pending_user_input_requests_json"], {}),
            pending_connect_requests=self._from_json(row["pending_connect_requests_json"], {}),
            deploy_connections=self._from_json(row["deploy_connections_json"], {}),
            deploy_state=self._from_json(row["deploy_state_json"], {}),
        )

    def _row_to_list_state(self, row: sqlite3.Row) -> PersistedSessionState:
        return PersistedSessionState(
            session_id=str(row["session_id"]),
            workspace=str(row["workspace"]),
            mode=str(row["mode"]),
            model=str(row["model"]),
            title=str(row["title"]),
            preview=str(row["preview"]),
            message_count=int(row["message_count"] or 0),
            tool_call_count=int(row["tool_call_count"] or 0),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            reasoning_effort=row["reasoning_effort"],
            execution_mode=str(row["execution_mode"] or "local"),
            base_workspace=row["base_workspace"],
            worktree_path=row["worktree_path"],
            worktree_branch=row["worktree_branch"],
            agent_type=str(row["agent_type"] or "coding"),
            phase=str(row["phase"] or "idle"),
        )

    def _load_open_files(self, connection: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
        session_id = str(row["session_id"])
        rows = connection.execute(
            """
            SELECT path
            FROM session_open_files
            WHERE session_id = ?
            ORDER BY position ASC
            """,
            (session_id,),
        ).fetchall()
        if rows:
            return [str(item["path"]) for item in rows]
        return self._from_json(row["open_files_json"], [])

    def _load_usage_map(self, connection: sqlite3.Connection, session_id: str) -> dict[str, dict[str, int]]:
        rows = connection.execute(
            """
            SELECT usage_scope, input_tokens, output_tokens, reasoning_tokens, cached_input_tokens, total_tokens
            FROM session_usage
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
        payload: dict[str, dict[str, int]] = {}
        for row in rows:
            payload[str(row["usage_scope"])] = {
                "inputTokens": int(row["input_tokens"] or 0),
                "outputTokens": int(row["output_tokens"] or 0),
                "reasoningTokens": int(row["reasoning_tokens"] or 0),
                "cachedInputTokens": int(row["cached_input_tokens"] or 0),
                "totalTokens": int(row["total_tokens"] or 0),
            }
        return payload

    def _load_messages(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_map = {
            str(tool.get("id") or ""): tool
            for tool in tool_calls
            if str(tool.get("id") or "").strip()
        }
        part_rows = connection.execute(
            """
            SELECT message_id, part_index, part_type, text_value, tool_call_id
            FROM session_message_parts
            WHERE session_id = ?
            ORDER BY message_id ASC, part_index ASC
            """,
            (session_id,),
        ).fetchall()
        parts_by_message: dict[str, list[dict[str, Any]]] = {}
        for row in part_rows:
            message_id = str(row["message_id"])
            part_type = str(row["part_type"])
            if part_type == "tool_call":
                tool_call_id = str(row["tool_call_id"] or "")
                tool_call = tool_map.get(tool_call_id)
                if tool_call is None:
                    continue
                part_payload = {"type": "tool_call", "toolCall": tool_call}
            elif part_type.startswith("data-"):
                part_payload = {
                    "type": "data",
                    "dataType": part_type,
                    "data": self._from_json(row["text_value"], {}),
                }
            else:
                part_payload = {
                    "type": part_type,
                    "text": str(row["text_value"] or ""),
                }
            parts_by_message.setdefault(message_id, []).append(part_payload)

        rows = connection.execute(
            """
            SELECT id, role, content, thought_text, metadata_json, created_at, turn_index, thinking_time, message_index
            FROM session_messages
            WHERE session_id = ?
            ORDER BY message_index ASC, created_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            message_id = str(row["id"])
            payload: dict[str, Any] = {
                "id": message_id,
                "role": str(row["role"]),
                "content": str(row["content"]),
            }
            metadata = self._from_json(row["metadata_json"], {})
            if isinstance(metadata, dict):
                payload.update(metadata)
            thoughts = str(row["thought_text"] or "")
            if thoughts:
                payload["thoughts"] = thoughts
            parts = parts_by_message.get(message_id, [])
            if parts:
                payload["parts"] = parts
                tool_parts = [
                    part.get("toolCall")
                    for part in parts
                    if isinstance(part, dict)
                    and part.get("type") == "tool_call"
                    and isinstance(part.get("toolCall"), dict)
                ]
                if tool_parts:
                    payload["toolCalls"] = tool_parts
            if row["turn_index"] is not None:
                payload["turnIndex"] = int(row["turn_index"])
            if row["thinking_time"] is not None:
                payload["thinkingTime"] = float(row["thinking_time"])
            messages.append(payload)
        return messages

    def _load_tool_calls(self, connection: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT id, assistant_id, tool_name, state, success, arguments_json, output_json,
                   error_message, summary, metadata_json, approval_json, input_request_json,
                   started_at, finished_at, turn_index, step_index, tool_index
            FROM session_tool_calls
            WHERE session_id = ?
            ORDER BY tool_index ASC, started_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        payloads: list[dict[str, Any]] = []
        for row in rows:
            tool: dict[str, Any] = {
                "id": str(row["id"]),
                "name": str(row["tool_name"]),
                "state": str(row["state"]),
                "arguments": self._from_json(row["arguments_json"], {}),
                "output": self._from_json(row["output_json"], None),
            }
            metadata = self._from_json(row["metadata_json"], {})
            if isinstance(metadata, dict):
                tool.update(metadata)
            if row["assistant_id"] is not None:
                tool["assistantId"] = row["assistant_id"]
            if row["success"] is not None:
                tool["success"] = bool(row["success"])
            if row["error_message"] is not None:
                tool["errorMessage"] = row["error_message"]
            if str(row["summary"] or "").strip():
                tool["summary"] = str(row["summary"])
            approval = self._from_json(row["approval_json"], None)
            if approval is not None:
                tool["approval"] = approval
            input_request = self._from_json(row["input_request_json"], None)
            if input_request is not None:
                tool["inputRequest"] = input_request
            if row["turn_index"] is not None:
                tool["turnIndex"] = int(row["turn_index"])
            if row["step_index"] is not None:
                tool["stepIndex"] = int(row["step_index"])
            payloads.append(tool)
        return payloads

    def _load_code_changes(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        *,
        include_large_fields: bool,
    ) -> list[dict[str, Any]]:
        artifact_rows = connection.execute(
            """
            SELECT metadata_json, path
            FROM session_artifacts
            WHERE session_id = ? AND kind = 'full_diff'
            """,
            (session_id,),
        ).fetchall()
        full_diff_by_change_id: dict[str, str] = {}
        for row in artifact_rows:
            metadata = self._from_json(row["metadata_json"], {})
            change_id = str(metadata.get("changeId") or "")
            file_path = str(row["path"] or "")
            if not change_id:
                continue
            if include_large_fields and file_path:
                try:
                    full_diff_by_change_id[change_id] = Path(file_path).read_text(encoding="utf-8")
                    continue
                except OSError:
                    pass
            full_diff_by_change_id[change_id] = str(metadata.get("preview") or "")

        rows = connection.execute(
            """
            SELECT id, tool_call_id, assistant_id, path, absolute_path, action, source,
                   lines_added, lines_deleted, summary, diff_preview, timestamp, turn_index, step_index
            FROM session_code_changes
            WHERE session_id = ?
            ORDER BY change_index ASC, timestamp ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payload: dict[str, Any] = {
                "id": str(row["id"]),
                "action": str(row["action"]),
                "path": str(row["path"]),
                "source": str(row["source"] or "agent"),
                "timestamp": int(row["timestamp"]),
                "linesAdded": int(row["lines_added"] or 0),
                "linesDeleted": int(row["lines_deleted"] or 0),
                "summary": str(row["summary"] or ""),
                "diffPreview": str(row["diff_preview"] or ""),
            }
            if row["tool_call_id"] is not None:
                payload["toolCallId"] = row["tool_call_id"]
            if row["assistant_id"] is not None:
                payload["assistantId"] = row["assistant_id"]
            if row["absolute_path"] is not None:
                payload["absolutePath"] = row["absolute_path"]
            if row["turn_index"] is not None:
                payload["turnIndex"] = int(row["turn_index"])
            if row["step_index"] is not None:
                payload["stepIndex"] = int(row["step_index"])
            payload["fullDiff"] = full_diff_by_change_id.get(payload["id"], payload["diffPreview"])
            payloads.append(payload)
        return payloads

    def _load_plan_steps(self, connection: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT id, title, description, status
            FROM session_plan_steps
            WHERE session_id = ?
            ORDER BY position ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "description": str(row["description"] or ""),
                "status": str(row["status"] or "pending"),
            }
            for row in rows
        ]

    def _load_terminal_output(self, connection: sqlite3.Connection, session_id: str) -> str:
        row = connection.execute(
            """
            SELECT path, metadata_json
            FROM session_artifacts
            WHERE session_id = ? AND kind = 'terminal_log'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return ""
        file_path = str(row["path"] or "")
        if file_path:
            try:
                return Path(file_path).read_text(encoding="utf-8")
            except OSError:
                pass
        metadata = self._from_json(row["metadata_json"], {})
        return str(metadata.get("preview") or "")

    def _legacy_row_to_state(self, row: sqlite3.Row) -> PersistedSessionState:
        legacy_plan_state = self._from_json(row["plan_state"] if "plan_state" in row.keys() else "{}", {})
        legacy_task_state = self._from_json(row["task_state"] if "task_state" in row.keys() else "{}", {})
        plan_state = self._merge_plan_and_task_state(legacy_plan_state, legacy_task_state)
        return self._normalize_state(
            PersistedSessionState(
                session_id=str(row["session_id"]),
                workspace=str(row["workspace"]),
                mode=str(row["mode"]),
                model=str(row["model"]),
                title=str(row["title"]),
                preview=str(row["preview"]),
                message_count=int(row["message_count"]),
                tool_call_count=int(row["tool_call_count"]),
                created_at=int(row["created_at"]),
                updated_at=int(row["updated_at"]),
                reasoning_effort=row["reasoning_effort"] if "reasoning_effort" in row.keys() else None,
                execution_mode=str(row["execution_mode"] if "execution_mode" in row.keys() else "local"),
                base_workspace=row["base_workspace"] if "base_workspace" in row.keys() else None,
                worktree_path=row["worktree_path"] if "worktree_path" in row.keys() else None,
                worktree_branch=row["worktree_branch"] if "worktree_branch" in row.keys() else None,
                agent_type=str(row["agent_type"] if "agent_type" in row.keys() else "coding"),
                phase=str(row["phase"] if "phase" in row.keys() else "idle"),
                route_state=self._from_json(row["route_state"] if "route_state" in row.keys() else "{}", {}),
                is_generating=bool(row["is_generating"]) if "is_generating" in row.keys() else False,
                startup_error=row["startup_error"] if "startup_error" in row.keys() else None,
                env_file=row["env_file"] if "env_file" in row.keys() else None,
                selected_file_path=row["selected_file_path"] if "selected_file_path" in row.keys() else None,
                open_files=self._from_json(row["open_files"] if "open_files" in row.keys() else "[]", []),
                terminal_output=str(row["terminal_output"] if "terminal_output" in row.keys() else ""),
                preview_url=str(row["preview_url"] if "preview_url" in row.keys() else ""),
                history_messages=self._from_json(row["history_messages"] if "history_messages" in row.keys() else "[]", []),
                history_tools=self._from_json(row["history_tools"] if "history_tools" in row.keys() else "[]", []),
                thoughts=self._from_json(row["thoughts"] if "thoughts" in row.keys() else "[]", []),
                token_usage=self._from_json(row["token_usage"] if "token_usage" in row.keys() else "{}", {}),
                cumulative_token_usage=self._from_json(row["cumulative_token_usage"] if "cumulative_token_usage" in row.keys() else "{}", {}),
                max_context_tokens=(int(row["max_context_tokens"]) if "max_context_tokens" in row.keys() and row["max_context_tokens"] is not None else None),
                plan_steps=self._from_json(row["plan_steps"] if "plan_steps" in row.keys() else "[]", []),
                plan_state=plan_state,
                code_changes=self._from_json(row["code_changes"] if "code_changes" in row.keys() else "[]", []),
                pending_delete_confirmations=self._from_json(row["pending_delete_confirmations"] if "pending_delete_confirmations" in row.keys() else "{}", {}),
                pending_commit_confirmations=self._from_json(row["pending_commit_confirmations"] if "pending_commit_confirmations" in row.keys() else "{}", {}),
                pending_tag_confirmations=self._from_json(row["pending_tag_confirmations"] if "pending_tag_confirmations" in row.keys() else "{}", {}),
                pending_user_input_requests=self._from_json(row["pending_user_input_requests"] if "pending_user_input_requests" in row.keys() else "{}", {}),
                pending_connect_requests=self._from_json(row["pending_connect_requests"] if "pending_connect_requests" in row.keys() else "{}", {}),
                deploy_connections=self._from_json(row["deploy_connections"] if "deploy_connections" in row.keys() else "{}", {}),
                deploy_state=self._from_json(row["deploy_state"] if "deploy_state" in row.keys() else "{}", {}),
            )
        )

    def _merge_plan_and_task_state(
        self,
        plan_state: object,
        task_state: object,
    ) -> dict[str, Any]:
        normalized = plan_state if isinstance(plan_state, dict) else {}
        tasks = normalized.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
        merged = {
            **normalized,
            "tasks": tasks,
            "active_task_id": normalized.get("active_task_id"),
            "active_step_id": normalized.get("active_step_id"),
            "pending_coding_input": normalized.get("pending_coding_input"),
        }
        if isinstance(task_state, dict):
            if not tasks and isinstance(task_state.get("tasks"), list):
                merged["tasks"] = task_state.get("tasks")
            if merged.get("active_task_id") is None and task_state.get("active_task_id") is not None:
                merged["active_task_id"] = task_state.get("active_task_id")
            if merged.get("active_step_id") is None and task_state.get("active_step_id") is not None:
                merged["active_step_id"] = task_state.get("active_step_id")
            if merged.get("pending_coding_input") is None and task_state.get("pending_coding_input") is not None:
                merged["pending_coding_input"] = task_state.get("pending_coding_input")
            if str(merged.get("status") or "").strip() == "" and task_state.get("status") is not None:
                merged["status"] = task_state.get("status")
        return merged

    def _raw_memory_item_to_record(
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
        now = (
            self._coerce_optional_int(raw_item.get("updatedAt"))
            or self._coerce_optional_int(raw_item.get("createdAt"))
            or 1
        )
        return MemoryItemRecord(
            id=str(raw_item.get("id") or uuid.uuid4().hex),
            scope="workspace" if scope == "workspace" else "global",
            workspace_key=workspace_key,
            content=content,
            enabled=bool(raw_item.get("enabled", True)),
            created_at=self._coerce_optional_int(raw_item.get("createdAt")) or now,
            updated_at=self._coerce_optional_int(raw_item.get("updatedAt")) or now,
            source_session_id=str(raw_item.get("sourceSessionId") or "") or None,
            source_preview=str(raw_item.get("sourcePreview") or "") or None,
        )

    def _row_to_memory_item(self, row: sqlite3.Row) -> MemoryItemRecord:
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

    def _normalize_state(self, state: PersistedSessionState) -> PersistedSessionState:
        normalized_messages = [
            self._normalize_message(message, state.session_id, index)
            for index, message in enumerate(state.history_messages, start=1)
            if isinstance(message, dict)
        ]
        normalized_tools = [
            self._normalize_tool(tool, state.session_id, index)
            for index, tool in enumerate(state.history_tools, start=1)
            if isinstance(tool, dict)
        ]
        normalized_changes = [
            self._normalize_code_change(change, state.session_id, index)
            for index, change in enumerate(state.code_changes, start=1)
            if isinstance(change, dict)
        ]
        normalized_plan_steps = [
            self._normalize_plan_step(step, state.session_id, index)
            for index, step in enumerate(state.plan_steps, start=1)
            if isinstance(step, dict)
        ]
        thoughts = self._rebuild_thoughts_from_messages(normalized_messages)
        return PersistedSessionState(
            session_id=state.session_id,
            workspace=state.workspace,
            mode=state.mode,
            model=state.model,
            title=state.title,
            preview=state.preview,
            message_count=state.message_count or len(normalized_messages),
            tool_call_count=state.tool_call_count or len(normalized_tools),
            created_at=state.created_at,
            updated_at=state.updated_at,
            reasoning_effort=state.reasoning_effort,
            execution_mode=state.execution_mode,
            base_workspace=state.base_workspace,
            worktree_path=state.worktree_path,
            worktree_branch=state.worktree_branch,
            agent_type=state.agent_type,
            phase=state.phase,
            route_state=state.route_state if isinstance(state.route_state, dict) else {},
            is_generating=state.is_generating,
            startup_error=state.startup_error,
            env_file=state.env_file,
            selected_file_path=state.selected_file_path,
            open_files=[str(path) for path in state.open_files if str(path).strip()],
            terminal_output=state.terminal_output or "",
            preview_url=state.preview_url or "",
            history_messages=normalized_messages,
            history_tools=normalized_tools,
            thoughts=thoughts,
            token_usage=self._normalize_usage_payload(state.token_usage),
            cumulative_token_usage=self._normalize_usage_payload(state.cumulative_token_usage),
            max_context_tokens=state.max_context_tokens,
            plan_steps=normalized_plan_steps,
            plan_state=state.plan_state if isinstance(state.plan_state, dict) else {},
            code_changes=normalized_changes,
            pending_delete_confirmations=state.pending_delete_confirmations if isinstance(state.pending_delete_confirmations, dict) else {},
            pending_commit_confirmations=state.pending_commit_confirmations if isinstance(state.pending_commit_confirmations, dict) else {},
            pending_tag_confirmations=state.pending_tag_confirmations if isinstance(state.pending_tag_confirmations, dict) else {},
            pending_user_input_requests=state.pending_user_input_requests if isinstance(state.pending_user_input_requests, dict) else {},
            pending_connect_requests=state.pending_connect_requests if isinstance(state.pending_connect_requests, dict) else {},
            deploy_connections=state.deploy_connections if isinstance(state.deploy_connections, dict) else {},
            deploy_state=state.deploy_state if isinstance(state.deploy_state, dict) else {},
        )

    def _normalize_message(
        self,
        message: dict[str, Any],
        session_id: str,
        index: int,
    ) -> dict[str, Any]:
        normalized = {**message}
        normalized["id"] = str(message.get("id") or f"{session_id}-message-{index}")
        normalized["role"] = str(message.get("role") or "")
        normalized["content"] = str(message.get("content") or "")
        self._normalize_metadata_aliases(normalized)
        if normalized["role"] != "assistant":
            normalized.pop("parts", None)
            normalized.pop("thoughts", None)
            normalized.pop("toolCalls", None)
            normalized.pop("thinkingTime", None)
            normalized.pop("startTime", None)
            return normalized

        thinking_time = self._coerce_optional_float(
            message.get("thinkingTime", message.get("thinking_time"))
        )
        if thinking_time is not None:
            normalized["thinkingTime"] = thinking_time
        else:
            normalized.pop("thinkingTime", None)
        parts = self._message_parts_for_storage(normalized)
        if parts:
            normalized["parts"] = parts
            tool_calls = [
                part.get("toolCall")
                for part in parts
                if isinstance(part, dict)
                and part.get("type") == "tool_call"
                and isinstance(part.get("toolCall"), dict)
            ]
            if tool_calls:
                normalized["toolCalls"] = tool_calls
            else:
                normalized.pop("toolCalls", None)
            thinking_parts = [
                str(part.get("text") or "").strip()
                for part in parts
                if isinstance(part, dict) and part.get("type") == "thinking" and str(part.get("text") or "").strip()
            ]
            if thinking_parts:
                normalized["thoughts"] = "\n\n".join(thinking_parts)
        return normalized

    def _normalize_tool(
        self,
        tool: dict[str, Any],
        session_id: str,
        index: int,
    ) -> dict[str, Any]:
        normalized = {**tool}
        normalized["id"] = str(tool.get("id") or f"{session_id}-tool-{index}")
        normalized["name"] = str(tool.get("name") or "")
        normalized["state"] = str(tool.get("state") or "")
        arguments = tool.get("arguments")
        normalized["arguments"] = arguments if isinstance(arguments, dict) else {}
        if "assistant_id" in normalized and "assistantId" not in normalized:
            normalized["assistantId"] = normalized.get("assistant_id")
        if "error_message" in normalized and "errorMessage" not in normalized:
            normalized["errorMessage"] = normalized.get("error_message")
        if "step_index" in normalized and "stepIndex" not in normalized:
            normalized["stepIndex"] = normalized.get("step_index")
        if "turn_index" in normalized and "turnIndex" not in normalized:
            normalized["turnIndex"] = normalized.get("turn_index")
        self._normalize_metadata_aliases(normalized)
        return normalized

    def _normalize_code_change(
        self,
        change: dict[str, Any],
        session_id: str,
        index: int,
    ) -> dict[str, Any]:
        normalized = {**change}
        normalized["id"] = str(change.get("id") or f"{session_id}-change-{index}")
        normalized["action"] = str(change.get("action") or "modified")
        normalized["path"] = str(change.get("path") or "")
        normalized["summary"] = str(change.get("summary") or "")
        normalized["source"] = str(change.get("source") or "agent")
        normalized["diffPreview"] = str(change.get("diffPreview", change.get("diff_preview")) or "")
        normalized["fullDiff"] = str(change.get("fullDiff", change.get("full_diff")) or normalized["diffPreview"])
        if "assistant_id" in normalized and "assistantId" not in normalized:
            normalized["assistantId"] = normalized.get("assistant_id")
        if "tool_call_id" in normalized and "toolCallId" not in normalized:
            normalized["toolCallId"] = normalized.get("tool_call_id")
        if "turn_index" in normalized and "turnIndex" not in normalized:
            normalized["turnIndex"] = normalized.get("turn_index")
        if "step_index" in normalized and "stepIndex" not in normalized:
            normalized["stepIndex"] = normalized.get("step_index")
        return normalized

    def _normalize_plan_step(
        self,
        step: dict[str, Any],
        session_id: str,
        index: int,
    ) -> dict[str, Any]:
        return {
            "id": str(step.get("id") or f"{session_id}-plan-step-{index}"),
            "title": str(step.get("title") or ""),
            "description": str(step.get("description") or ""),
            "status": str(step.get("status") or "pending"),
        }

    def _normalize_metadata_aliases(self, payload: dict[str, Any]) -> None:
        aliases = {
            "agent_scope": "agentScope",
            "subagent_id": "subagentId",
            "parent_tool_call_id": "parentToolCallId",
            "parent_assistant_id": "parentAssistantId",
            "subagent_title": "subagentTitle",
            "subagent_task": "subagentTask",
        }
        for snake_key, camel_key in aliases.items():
            if snake_key in payload and camel_key not in payload:
                payload[camel_key] = payload.get(snake_key)

    def _metadata_payload(self, payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        self._normalize_metadata_aliases(payload)
        metadata: dict[str, Any] = {}
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                if not value:
                    continue
                metadata[key] = value
                continue
            if isinstance(value, (bool, int, float, list, dict)):
                metadata[key] = value
        return metadata

    def _normalize_usage_payload(self, payload: object) -> dict[str, int]:
        if not isinstance(payload, dict):
            return self._empty_usage_payload()
        normalized = self._empty_usage_payload()
        for key in normalized:
            value = payload.get(key)
            if isinstance(value, bool):
                normalized[key] = int(value)
            elif isinstance(value, (int, float)):
                normalized[key] = max(int(value), 0)
        if normalized["totalTokens"] == 0:
            normalized["totalTokens"] = normalized["inputTokens"] + normalized["outputTokens"]
        return normalized

    def _extract_message_thoughts(self, message: dict[str, Any]) -> str:
        direct = str(message.get("thoughts") or "").strip()
        if direct:
            return direct
        parts = message.get("parts")
        if not isinstance(parts, list):
            return ""
        thought_parts = [
            str(part.get("text") or "").strip()
            for part in parts
            if isinstance(part, dict) and part.get("type") == "thinking" and str(part.get("text") or "").strip()
        ]
        return "\n\n".join(thought_parts)

    def _message_parts_for_storage(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        raw_parts = message.get("parts")
        if isinstance(raw_parts, list) and raw_parts:
            normalized_parts: list[dict[str, Any]] = []
            for part in raw_parts:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip()
                if part_type in {"text", "thinking"}:
                    normalized_parts.append(
                        {
                            "type": part_type,
                            "text": str(part.get("text") or ""),
                        }
                    )
                elif part_type == "tool_call" and isinstance(part.get("toolCall"), dict):
                    normalized_parts.append(
                        {
                            "type": "tool_call",
                            "toolCall": self._normalize_tool(
                                part["toolCall"],
                                str(message.get("id") or "message"),
                                len(normalized_parts) + 1,
                            ),
                        }
                    )
                elif (
                    part_type == "data"
                    and isinstance(part.get("dataType"), str)
                    and str(part.get("dataType")).startswith("data-")
                ):
                    normalized_parts.append(
                        {
                            "type": "data",
                            "dataType": str(part.get("dataType")),
                            "data": part.get("data"),
                        }
                    )
            if normalized_parts:
                return normalized_parts

        parts: list[dict[str, Any]] = []
        thought_text = str(message.get("thoughts") or "").strip()
        if thought_text:
            parts.append({"type": "thinking", "text": thought_text})
        tool_calls = message.get("toolCalls")
        if isinstance(tool_calls, list):
            for tool_index, tool_call in enumerate(tool_calls, start=1):
                if isinstance(tool_call, dict):
                    parts.append(
                        {
                            "type": "tool_call",
                            "toolCall": self._normalize_tool(
                                tool_call,
                                str(message.get("id") or "message"),
                                tool_index,
                            ),
                        }
                    )
        content = str(message.get("content") or "")
        if content:
            parts.append({"type": "text", "text": content})
        return parts

    def _extract_tool_call_id(self, part: dict[str, Any]) -> str | None:
        tool_call = part.get("toolCall")
        if not isinstance(tool_call, dict):
            return None
        tool_id = str(tool_call.get("id") or "").strip()
        return tool_id or None

    def _rebuild_thoughts_from_messages(self, messages: list[dict[str, Any]]) -> list[str]:
        thoughts: list[str] = []
        for message in messages:
            direct = str(message.get("thoughts") or "").strip()
            if direct:
                thoughts.append(direct)
                continue
            parts = message.get("parts")
            if not isinstance(parts, list):
                continue
            thought_parts = [
                str(part.get("text") or "").strip()
                for part in parts
                if isinstance(part, dict)
                and part.get("type") == "thinking"
                and str(part.get("text") or "").strip()
            ]
            if thought_parts:
                thoughts.append("\n\n".join(thought_parts))
        return thoughts

    def _empty_usage_payload(self) -> dict[str, int]:
        return {
            "inputTokens": 0,
            "outputTokens": 0,
            "reasoningTokens": 0,
            "cachedInputTokens": 0,
            "totalTokens": 0,
        }

    def _tool_summary(self, tool: dict[str, Any]) -> str:
        summary = str(tool.get("summary") or "").strip()
        if summary:
            return summary
        return f"{str(tool.get('name') or 'tool')} [{str(tool.get('state') or '')}]".strip()

    def _table_exists(self, connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    def _drop_session_tables(
        self,
        connection: sqlite3.Connection,
        *,
        keep_legacy: bool = False,
    ) -> None:
        tables = [
            "session_artifacts",
            "session_plan_steps",
            "session_code_changes",
            "session_tool_calls",
            "session_message_parts",
            "session_messages",
            "session_usage",
            "session_open_files",
            "sessions",
        ]
        if not keep_legacy:
            tables.append(LEGACY_SESSIONS_TABLE)
        for table_name in tables:
            connection.execute(f"DROP TABLE IF EXISTS {table_name}")

    def _has_schema_migration(self, connection: sqlite3.Connection, key: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE key = ?",
            (key,),
        ).fetchone()
        return row is not None

    def _mark_schema_migration(self, connection: sqlite3.Connection, key: str) -> None:
        connection.execute(
            """
            INSERT INTO schema_migrations (key, applied_at)
            VALUES (?, strftime('%s','now') * 1000)
            ON CONFLICT(key) DO NOTHING
            """,
            (key,),
        )

    def _session_artifacts_dir(self, workspace: str, session_id: str) -> Path:
        workspace_root = Path(workspace).expanduser()
        try:
            resolved_workspace = workspace_root.resolve()
        except OSError:
            resolved_workspace = workspace_root
        preferred_root = resolved_workspace / ".supercode" / "artifacts" / "sessions"
        try:
            preferred_root.mkdir(parents=True, exist_ok=True)
            return preferred_root / session_id
        except OSError:
            fallback_root = self.db_path.parent / "artifacts" / "sessions"
            fallback_root.mkdir(parents=True, exist_ok=True)
            return fallback_root / session_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _coerce_optional_int(self, value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _coerce_optional_float(self, value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coerce_optional_bool(self, value: object) -> int | None:
        if isinstance(value, bool):
            return 1 if value else 0
        return None

    def _to_json(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _from_json(self, value: object, fallback: Any) -> Any:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str) or not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
