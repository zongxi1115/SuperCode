from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException


DEFAULT_KANBAN_COLUMNS = (
    ("Backlog", "backlog"),
    ("Todo", "todo"),
    ("In Progress", "in_progress"),
    ("Done", "done"),
)
ALLOWED_PRIORITIES = {"none", "low", "medium", "high", "urgent"}
FRONTEND_PRIORITY_MAP = {
    "Low": "low",
    "Medium": "medium",
    "High": "high",
    "Critical": "urgent",
}


class KanbanStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def list_boards(self, workspace: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, workspace, name, description, created_at, updated_at
                FROM kanban_boards
                WHERE workspace = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (workspace,),
            ).fetchall()
        return [self._board_payload(row) for row in rows]

    def create_board(self, workspace: str, name: str, description: str | None = None) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise HTTPException(status_code=400, detail="看板名称不能为空。")

        board_id = f"board_{uuid.uuid4().hex[:12]}"
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO kanban_boards (id, workspace, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (board_id, workspace, normalized_name, self._clean_optional(description), now, now),
            )
            for index, (column_name, status_key) in enumerate(DEFAULT_KANBAN_COLUMNS):
                connection.execute(
                    """
                    INSERT INTO kanban_columns (id, board_id, name, status_key, position, wip_limit)
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    (f"column_{uuid.uuid4().hex[:12]}", board_id, column_name, status_key, index),
                )
        return self.get_board(workspace, board_id)

    def get_or_create_default_board(self, workspace: str) -> dict[str, Any]:
        boards = self.list_boards(workspace)
        if boards:
            return self.get_board(workspace, str(boards[0]["id"]))
        return self.create_board(workspace, "默认看板", None)

    def get_board(self, workspace: str, board_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            board_row = connection.execute(
                """
                SELECT id, workspace, name, description, created_at, updated_at
                FROM kanban_boards
                WHERE id = ? AND workspace = ?
                """,
                (board_id, workspace),
            ).fetchone()
            if board_row is None:
                raise HTTPException(status_code=404, detail="看板不存在。")
            column_rows = connection.execute(
                """
                SELECT id, board_id, name, status_key, position, wip_limit
                FROM kanban_columns
                WHERE board_id = ?
                ORDER BY position ASC, name ASC
                """,
                (board_id,),
            ).fetchall()
            card_rows = connection.execute(
                """
                SELECT id, board_id, column_id, title, description, priority, labels, assignee,
                       position, ai_state, created_at, updated_at
                FROM kanban_cards
                WHERE board_id = ?
                ORDER BY position ASC, created_at ASC
                """,
                (board_id,),
            ).fetchall()

        columns = [self._column_payload(row) for row in column_rows]
        column_status_by_id = {str(column["id"]): str(column["name"]) for column in columns}
        cards = [self._card_payload(row, column_status_by_id) for row in card_rows]
        board = self._board_payload(board_row)
        board["columns"] = columns
        board["cards"] = cards
        return board

    def create_card(
        self,
        workspace: str,
        *,
        board_id: str,
        title: str,
        column_id: str | None = None,
        status: str | None = None,
        description: str | None = None,
        priority: str = "none",
        labels: list[str] | None = None,
        assignee: str | None = None,
    ) -> dict[str, Any]:
        normalized_title = str(title or "").strip()
        if not normalized_title:
            raise HTTPException(status_code=400, detail="卡片标题不能为空。")

        normalized_priority = self._normalize_priority(priority)
        normalized_labels = self._normalize_labels(labels)
        now = self._now()
        card_id = f"card_{uuid.uuid4().hex[:12]}"

        with self._lock, self._connect() as connection:
            self._require_board(connection, workspace, board_id)
            target_column = self._resolve_column(connection, board_id, column_id=column_id, status=status)
            position = self._next_card_position(connection, board_id, str(target_column["id"]))
            connection.execute(
                """
                INSERT INTO kanban_cards (
                    id, board_id, column_id, title, description, priority, labels, assignee,
                    position, ai_state, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    board_id,
                    str(target_column["id"]),
                    normalized_title,
                    self._clean_optional(description),
                    normalized_priority,
                    json.dumps(normalized_labels, ensure_ascii=False),
                    self._clean_optional(assignee),
                    position,
                    None,
                    now,
                    now,
                ),
            )
            self._touch_board(connection, board_id, now)

        return self.get_card(workspace, card_id)

    def get_card(self, workspace: str, card_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT cards.id, cards.board_id, cards.column_id, cards.title, cards.description,
                       cards.priority, cards.labels, cards.assignee, cards.position, cards.ai_state,
                       cards.created_at, cards.updated_at
                FROM kanban_cards AS cards
                JOIN kanban_boards AS boards ON boards.id = cards.board_id
                WHERE cards.id = ? AND boards.workspace = ?
                """,
                (card_id, workspace),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="卡片不存在。")
            column_rows = connection.execute(
                "SELECT id, name FROM kanban_columns WHERE board_id = ?",
                (str(row["board_id"]),),
            ).fetchall()
        return self._card_payload(row, {str(column["id"]): str(column["name"]) for column in column_rows})

    def update_card(
        self,
        workspace: str,
        card_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        assignee: str | None = None,
        column_id: str | None = None,
        status: str | None = None,
        position: float | None = None,
        ai_state: dict[str, Any] | None | object = ...,
    ) -> dict[str, Any]:
        now = self._now()
        with self._lock, self._connect() as connection:
            row = self._require_card(connection, workspace, card_id)
            board_id = str(row["board_id"])
            next_column_id = str(row["column_id"])
            if column_id is not None or status is not None:
                next_column = self._resolve_column(connection, board_id, column_id=column_id, status=status)
                next_column_id = str(next_column["id"])

            updates: dict[str, Any] = {
                "column_id": next_column_id,
                "updated_at": now,
            }
            if title is not None:
                normalized_title = str(title).strip()
                if not normalized_title:
                    raise HTTPException(status_code=400, detail="卡片标题不能为空。")
                updates["title"] = normalized_title
            if description is not None:
                updates["description"] = self._clean_optional(description)
            if priority is not None:
                updates["priority"] = self._normalize_priority(priority)
            if labels is not None:
                updates["labels"] = json.dumps(self._normalize_labels(labels), ensure_ascii=False)
            if assignee is not None:
                updates["assignee"] = self._clean_optional(assignee)
            if position is not None:
                updates["position"] = float(position)
            elif next_column_id != str(row["column_id"]):
                updates["position"] = self._next_card_position(connection, board_id, next_column_id)
            if ai_state is not ...:
                updates["ai_state"] = self._dump_ai_state(ai_state)

            set_clause = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(
                f"UPDATE kanban_cards SET {set_clause} WHERE id = ?",
                (*updates.values(), card_id),
            )
            self._touch_board(connection, board_id, now)

        return self.get_card(workspace, card_id)

    def reorder_cards(
        self,
        workspace: str,
        *,
        board_id: str,
        card_id: str | None = None,
        column_id: str | None = None,
        target_column_id: str | None = None,
        ordered_card_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_card_ids = [str(value).strip() for value in (ordered_card_ids or []) if str(value).strip()]
        now = self._now()
        with self._lock, self._connect() as connection:
            self._require_board(connection, workspace, board_id)
            target_column = self._resolve_column(
                connection,
                board_id,
                column_id=target_column_id or column_id,
                status=None,
            )
            target_column_id_value = str(target_column["id"])

            if card_id:
                self._require_card(connection, workspace, card_id)
                if card_id not in normalized_card_ids:
                    normalized_card_ids.append(card_id)

            if not normalized_card_ids:
                raise HTTPException(status_code=400, detail="缺少需要排序的卡片。")

            placeholders = ",".join("?" for _ in normalized_card_ids)
            rows = connection.execute(
                f"""
                SELECT cards.id
                FROM kanban_cards AS cards
                JOIN kanban_boards AS boards ON boards.id = cards.board_id
                WHERE cards.id IN ({placeholders}) AND cards.board_id = ? AND boards.workspace = ?
                """,
                (*normalized_card_ids, board_id, workspace),
            ).fetchall()
            existing_ids = {str(row["id"]) for row in rows}
            missing_ids = [value for value in normalized_card_ids if value not in existing_ids]
            if missing_ids:
                raise HTTPException(status_code=404, detail="排序中包含不存在的卡片。")

            for index, current_card_id in enumerate(normalized_card_ids):
                connection.execute(
                    """
                    UPDATE kanban_cards
                    SET column_id = ?, position = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (target_column_id_value, index, now, current_card_id),
                )
            self._touch_board(connection, board_id, now)

        return self.get_board(workspace, board_id)

    def delete_card(self, workspace: str, card_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = self._require_card(connection, workspace, card_id)
            board_id = str(row["board_id"])
            now = self._now()
            connection.execute("DELETE FROM kanban_cards WHERE id = ?", (card_id,))
            self._touch_board(connection, board_id, now)
        return {"ok": True, "deleted": True, "cardId": card_id}

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kanban_boards (
                    id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kanban_columns (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status_key TEXT NOT NULL,
                    position REAL NOT NULL,
                    wip_limit INTEGER,
                    FOREIGN KEY(board_id) REFERENCES kanban_boards(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS kanban_cards (
                    id TEXT PRIMARY KEY,
                    board_id TEXT NOT NULL,
                    column_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    priority TEXT NOT NULL,
                    labels TEXT NOT NULL DEFAULT '[]',
                    assignee TEXT,
                    position REAL NOT NULL,
                    ai_state TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(board_id) REFERENCES kanban_boards(id) ON DELETE CASCADE,
                    FOREIGN KEY(column_id) REFERENCES kanban_columns(id) ON DELETE CASCADE
                )
                """
            )
            existing_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(kanban_cards)").fetchall()
            }
            if "ai_state" not in existing_columns:
                connection.execute("ALTER TABLE kanban_cards ADD COLUMN ai_state TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kanban_boards_workspace ON kanban_boards(workspace)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kanban_columns_board ON kanban_columns(board_id, position)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_kanban_cards_board_column ON kanban_cards(board_id, column_id, position)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _require_board(self, connection: sqlite3.Connection, workspace: str, board_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT id FROM kanban_boards WHERE id = ? AND workspace = ?",
            (board_id, workspace),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="看板不存在。")
        return row

    def _require_card(self, connection: sqlite3.Connection, workspace: str, card_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT cards.id, cards.board_id, cards.column_id, cards.position
            FROM kanban_cards AS cards
            JOIN kanban_boards AS boards ON boards.id = cards.board_id
            WHERE cards.id = ? AND boards.workspace = ?
            """,
            (card_id, workspace),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="卡片不存在。")
        return row

    def _resolve_column(
        self,
        connection: sqlite3.Connection,
        board_id: str,
        *,
        column_id: str | None,
        status: str | None,
    ) -> sqlite3.Row:
        if column_id:
            row = connection.execute(
                "SELECT id, name FROM kanban_columns WHERE id = ? AND board_id = ?",
                (column_id, board_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="列不存在。")
            return row

        normalized_status = str(status or "").strip()
        if normalized_status:
            row = connection.execute(
                """
                SELECT id, name
                FROM kanban_columns
                WHERE board_id = ? AND (name = ? OR status_key = ?)
                """,
                (board_id, normalized_status, normalized_status.lower().replace(" ", "_")),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="状态列不存在。")
            return row

        row = connection.execute(
            """
            SELECT id, name
            FROM kanban_columns
            WHERE board_id = ?
            ORDER BY position ASC
            LIMIT 1
            """,
            (board_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="看板没有可用列。")
        return row

    def _next_card_position(self, connection: sqlite3.Connection, board_id: str, column_id: str) -> float:
        row = connection.execute(
            """
            SELECT MAX(position) AS max_position
            FROM kanban_cards
            WHERE board_id = ? AND column_id = ?
            """,
            (board_id, column_id),
        ).fetchone()
        if row is None or row["max_position"] is None:
            return 0
        return float(row["max_position"]) + 1

    def _touch_board(self, connection: sqlite3.Connection, board_id: str, timestamp: int) -> None:
        connection.execute(
            "UPDATE kanban_boards SET updated_at = ? WHERE id = ?",
            (timestamp, board_id),
        )

    def _board_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "workspace": str(row["workspace"]),
            "name": str(row["name"]),
            "description": row["description"],
            "createdAt": self._timestamp_to_iso(int(row["created_at"])),
            "updatedAt": self._timestamp_to_iso(int(row["updated_at"])),
        }

    def _column_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        position = float(row["position"])
        return {
            "id": str(row["id"]),
            "boardId": str(row["board_id"]),
            "name": str(row["name"]),
            "statusKey": str(row["status_key"]),
            "position": position,
            "order": int(position),
            "wipLimit": row["wip_limit"],
        }

    def _card_payload(self, row: sqlite3.Row, column_status_by_id: dict[str, str]) -> dict[str, Any]:
        column_id = str(row["column_id"])
        position = float(row["position"])
        return {
            "id": str(row["id"]),
            "boardId": str(row["board_id"]),
            "columnId": column_id,
            "title": str(row["title"]),
            "description": str(row["description"] or ""),
            "status": column_status_by_id.get(column_id, ""),
            "priority": str(row["priority"]),
            "labels": self._load_labels(row["labels"]),
            "assignee": row["assignee"],
            "position": position,
            "aiState": self._load_ai_state(row["ai_state"]),
            "createdAt": self._timestamp_to_iso(int(row["created_at"])),
            "updatedAt": self._timestamp_to_iso(int(row["updated_at"])),
        }

    @staticmethod
    def _normalize_priority(priority: str | None) -> str:
        raw = str(priority or "none").strip()
        normalized = FRONTEND_PRIORITY_MAP.get(raw, raw.lower())
        if normalized not in ALLOWED_PRIORITIES:
            raise HTTPException(status_code=400, detail="卡片优先级无效。")
        return normalized

    @staticmethod
    def _normalize_labels(labels: list[str] | None) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for value in labels or []:
            label = str(value or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            normalized.append(label)
        return normalized

    @staticmethod
    def _load_labels(value: object) -> list[str]:
        if not isinstance(value, str):
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed if str(item).strip()]

    @staticmethod
    def _load_ai_state(value: object) -> dict[str, Any] | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _dump_ai_state(value: dict[str, Any] | None | object) -> str | None:
        if value is None:
            return None
        if value is ...:
            return None
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="卡片 AI 状态格式无效。")
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _now() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _timestamp_to_iso(timestamp_ms: int) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp_ms / 1000))
