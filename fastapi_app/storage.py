from __future__ import annotations

from fastapi_app.app_config import STATE_DB_PATH
from fastapi_app.kanban_store import KanbanStore
from fastapi_app.memory_store import SQLiteMemoryStore
from fastapi_app.session_store import SQLiteSessionStore

SESSION_STORE = SQLiteSessionStore(STATE_DB_PATH)
MEMORY_STORE = SQLiteMemoryStore(STATE_DB_PATH)
KANBAN_STORE = KanbanStore(STATE_DB_PATH)
