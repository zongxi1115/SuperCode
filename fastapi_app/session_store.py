from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    agent_type: str = "coding"
    phase: str = "idle"
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


class SessionStateAdapter(ABC):
    """Persistence adapter boundary for session state storage."""

    @abstractmethod
    def save(self, state: PersistedSessionState) -> None:
        raise NotImplementedError

    @abstractmethod
    def load(self, session_id: str) -> PersistedSessionState | None:
        raise NotImplementedError

    @abstractmethod
    def list(self) -> list[PersistedSessionState]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, session_id: str) -> None:
        raise NotImplementedError


class SQLiteSessionStateAdapter(SessionStateAdapter):
    """SQLite-backed session persistence.

    The rest of the app depends only on SessionStateAdapter, so another database
    can implement the same methods without changing the API layer.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def save(self, state: PersistedSessionState) -> None:
        payload = self._state_to_row(state)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id, workspace, mode, model, agent_type, phase, title, preview,
                    reasoning_effort,
                    message_count, tool_call_count, created_at, updated_at,
                    is_generating,
                    startup_error, env_file, selected_file_path, open_files,
                    terminal_output, preview_url, history_messages,
                    history_tools, thoughts, token_usage, cumulative_token_usage, max_context_tokens,
                    plan_steps, plan_state, code_changes, pending_delete_confirmations,
                    pending_commit_confirmations, pending_tag_confirmations,
                    pending_user_input_requests, pending_connect_requests, deploy_connections, deploy_state
                )
                VALUES (
                    :session_id, :workspace, :mode, :model, :agent_type, :phase, :title, :preview,
                    :reasoning_effort,
                    :message_count, :tool_call_count, :created_at, :updated_at,
                    :is_generating,
                    :startup_error, :env_file, :selected_file_path, :open_files,
                    :terminal_output, :preview_url, :history_messages,
                    :history_tools, :thoughts, :token_usage, :cumulative_token_usage, :max_context_tokens,
                    :plan_steps, :plan_state, :code_changes, :pending_delete_confirmations,
                    :pending_commit_confirmations, :pending_tag_confirmations,
                    :pending_user_input_requests, :pending_connect_requests, :deploy_connections, :deploy_state
                )
                ON CONFLICT(session_id) DO UPDATE SET
                    workspace = excluded.workspace,
                    mode = excluded.mode,
                    model = excluded.model,
                    reasoning_effort = excluded.reasoning_effort,
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
                    open_files = excluded.open_files,
                    terminal_output = excluded.terminal_output,
                    preview_url = excluded.preview_url,
                    history_messages = excluded.history_messages,
                    history_tools = excluded.history_tools,
                    thoughts = excluded.thoughts,
                    token_usage = excluded.token_usage,
                    cumulative_token_usage = excluded.cumulative_token_usage,
                    max_context_tokens = excluded.max_context_tokens,
                    plan_steps = excluded.plan_steps,
                    plan_state = excluded.plan_state,
                    code_changes = excluded.code_changes,
                    pending_delete_confirmations = excluded.pending_delete_confirmations,
                    pending_commit_confirmations = excluded.pending_commit_confirmations,
                    pending_tag_confirmations = excluded.pending_tag_confirmations,
                    pending_user_input_requests = excluded.pending_user_input_requests,
                    pending_connect_requests = excluded.pending_connect_requests,
                    deploy_connections = excluded.deploy_connections,
                    deploy_state = excluded.deploy_state
                """,
                payload,
            )

    def load(self, session_id: str) -> PersistedSessionState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._row_to_state(row) if row is not None else None

    def list(self) -> list[PersistedSessionState]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def delete(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reasoning_effort TEXT,
                    agent_type TEXT NOT NULL DEFAULT 'coding',
                    phase TEXT NOT NULL DEFAULT 'idle',
                    title TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    tool_call_count INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    is_generating INTEGER NOT NULL DEFAULT 0,
                    startup_error TEXT,
                    env_file TEXT,
                    selected_file_path TEXT,
                    open_files TEXT NOT NULL,
                    terminal_output TEXT NOT NULL,
                    preview_url TEXT NOT NULL,
                    history_messages TEXT NOT NULL,
                    history_tools TEXT NOT NULL,
                    thoughts TEXT NOT NULL,
                    token_usage TEXT NOT NULL DEFAULT '{}',
                    cumulative_token_usage TEXT NOT NULL DEFAULT '{}',
                    max_context_tokens INTEGER,
                    plan_steps TEXT NOT NULL,
                    plan_state TEXT NOT NULL DEFAULT '{}',
                    code_changes TEXT NOT NULL DEFAULT '[]',
                    pending_delete_confirmations TEXT NOT NULL,
                    pending_commit_confirmations TEXT NOT NULL DEFAULT '{}',
                    pending_tag_confirmations TEXT NOT NULL DEFAULT '{}',
                    pending_user_input_requests TEXT NOT NULL DEFAULT '{}',
                    pending_connect_requests TEXT NOT NULL DEFAULT '{}',
                    deploy_connections TEXT NOT NULL DEFAULT '{}',
                    deploy_state TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            existing_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "is_generating" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN is_generating INTEGER NOT NULL DEFAULT 0"
                )
            if "pending_commit_confirmations" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN pending_commit_confirmations TEXT NOT NULL DEFAULT '{}'"
                )
            if "pending_tag_confirmations" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN pending_tag_confirmations TEXT NOT NULL DEFAULT '{}'"
                )
            if "agent_type" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN agent_type TEXT NOT NULL DEFAULT 'coding'"
                )
            if "reasoning_effort" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN reasoning_effort TEXT"
                )
            if "phase" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN phase TEXT NOT NULL DEFAULT 'idle'"
                )
            if "pending_connect_requests" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN pending_connect_requests TEXT NOT NULL DEFAULT '{}'"
                )
            if "plan_state" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN plan_state TEXT NOT NULL DEFAULT '{}'"
                )
            if "pending_user_input_requests" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN pending_user_input_requests TEXT NOT NULL DEFAULT '{}'"
                )
            if "code_changes" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN code_changes TEXT NOT NULL DEFAULT '[]'"
                )
            if "deploy_connections" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN deploy_connections TEXT NOT NULL DEFAULT '{}'"
                )
            if "deploy_state" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN deploy_state TEXT NOT NULL DEFAULT '{}'"
                )
            if "token_usage" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN token_usage TEXT NOT NULL DEFAULT '{}'"
                )
            if "cumulative_token_usage" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN cumulative_token_usage TEXT NOT NULL DEFAULT '{}'"
                )
            if "max_context_tokens" not in existing_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN max_context_tokens INTEGER"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC)"
            )

    def _state_to_row(self, state: PersistedSessionState) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "workspace": state.workspace,
            "mode": state.mode,
            "model": state.model,
            "reasoning_effort": state.reasoning_effort,
            "agent_type": state.agent_type,
            "phase": state.phase,
            "title": state.title,
            "preview": state.preview,
            "message_count": state.message_count,
            "tool_call_count": state.tool_call_count,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "is_generating": 1 if state.is_generating else 0,
            "startup_error": state.startup_error,
            "env_file": state.env_file,
            "selected_file_path": state.selected_file_path,
            "open_files": self._to_json(state.open_files),
            "terminal_output": state.terminal_output,
            "preview_url": state.preview_url,
            "history_messages": self._to_json(state.history_messages),
            "history_tools": self._to_json(state.history_tools),
            "thoughts": self._to_json(state.thoughts),
            "token_usage": self._to_json(state.token_usage),
            "cumulative_token_usage": self._to_json(state.cumulative_token_usage),
            "max_context_tokens": state.max_context_tokens,
            "plan_steps": self._to_json(state.plan_steps),
            "plan_state": self._to_json(state.plan_state),
            "code_changes": self._to_json(state.code_changes),
            "pending_delete_confirmations": self._to_json(state.pending_delete_confirmations),
            "pending_commit_confirmations": self._to_json(state.pending_commit_confirmations),
            "pending_tag_confirmations": self._to_json(state.pending_tag_confirmations),
            "pending_user_input_requests": self._to_json(state.pending_user_input_requests),
            "pending_connect_requests": self._to_json(state.pending_connect_requests),
            "deploy_connections": self._to_json(state.deploy_connections),
            "deploy_state": self._to_json(state.deploy_state),
        }

    def _row_to_state(self, row: sqlite3.Row) -> PersistedSessionState:
        return PersistedSessionState(
            session_id=str(row["session_id"]),
            workspace=str(row["workspace"]),
            mode=str(row["mode"]),
            model=str(row["model"]),
            reasoning_effort=row["reasoning_effort"] if "reasoning_effort" in row.keys() else None,
            agent_type=str(row["agent_type"] if "agent_type" in row.keys() else "coding"),
            phase=str(row["phase"] if "phase" in row.keys() else "idle"),
            title=str(row["title"]),
            preview=str(row["preview"]),
            message_count=int(row["message_count"]),
            tool_call_count=int(row["tool_call_count"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            is_generating=bool(row["is_generating"]),
            startup_error=row["startup_error"],
            env_file=row["env_file"],
            selected_file_path=row["selected_file_path"],
            open_files=self._from_json(row["open_files"], []),
            terminal_output=str(row["terminal_output"]),
            preview_url=str(row["preview_url"]),
            history_messages=self._from_json(row["history_messages"], []),
            history_tools=self._from_json(row["history_tools"], []),
            thoughts=self._from_json(row["thoughts"], []),
            token_usage=self._from_json(row["token_usage"] if "token_usage" in row.keys() else "{}", {}),
            cumulative_token_usage=self._from_json(
                row["cumulative_token_usage"] if "cumulative_token_usage" in row.keys() else "{}",
                {},
            ),
            max_context_tokens=(
                int(row["max_context_tokens"])
                if "max_context_tokens" in row.keys() and row["max_context_tokens"] is not None
                else None
            ),
            plan_steps=self._from_json(row["plan_steps"], []),
            plan_state=self._from_json(row["plan_state"] if "plan_state" in row.keys() else "{}", {}),
            code_changes=self._from_json(row["code_changes"] if "code_changes" in row.keys() else "[]", []),
            pending_delete_confirmations=self._from_json(row["pending_delete_confirmations"], {}),
            pending_commit_confirmations=self._from_json(row["pending_commit_confirmations"] if "pending_commit_confirmations" in row.keys() else "{}", {}),
            pending_tag_confirmations=self._from_json(row["pending_tag_confirmations"] if "pending_tag_confirmations" in row.keys() else "{}", {}),
            pending_user_input_requests=self._from_json(row["pending_user_input_requests"] if "pending_user_input_requests" in row.keys() else "{}", {}),
            pending_connect_requests=self._from_json(row["pending_connect_requests"] if "pending_connect_requests" in row.keys() else "{}", {}),
            deploy_connections=self._from_json(row["deploy_connections"] if "deploy_connections" in row.keys() else "{}", {}),
            deploy_state=self._from_json(row["deploy_state"] if "deploy_state" in row.keys() else "{}", {}),
        )

    def _to_json(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _from_json(self, value: object, fallback: Any) -> Any:
        if not isinstance(value, str) or not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
