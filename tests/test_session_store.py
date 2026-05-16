import tempfile
import unittest
from pathlib import Path

from fastapi_app import main as api_main
from fastapi_app.session_store import PersistedSessionState, SQLiteSessionStateAdapter


class SessionStoreTests(unittest.TestCase):
    def test_sqlite_adapter_round_trips_session_state(self) -> None:
        db_path = Path(tempfile.mkdtemp(prefix="supercode-session-store-")) / "state.sqlite3"
        adapter = SQLiteSessionStateAdapter(db_path)
        state = PersistedSessionState(
            session_id="session-1",
            workspace="D:/demo",
            mode="agent",
            model="demo-model",
            title="hello",
            preview="world",
            message_count=2,
            tool_call_count=1,
            created_at=100,
            updated_at=200,
            history_messages=[
                {"id": "u1", "role": "user", "content": "你好"},
                {"id": "a1", "role": "assistant", "content": "收到"},
            ],
            history_tools=[{"id": "t1", "name": "read_file", "state": "completed"}],
            thoughts=["先看文件"],
            plan_steps=[{"id": "1", "title": "done", "status": "completed"}],
        )

        adapter.save(state)
        loaded = adapter.load("session-1")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.history_messages[1]["content"], "收到")
        self.assertEqual(loaded.history_tools[0]["name"], "read_file")
        self.assertEqual(adapter.list()[0].session_id, "session-1")

        adapter.delete("session-1")

        self.assertIsNone(adapter.load("session-1"))

    def test_empty_new_session_is_not_persisted_until_it_has_interaction(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-empty-session-")).resolve()
        session = api_main.UISession(
            session_id="session-empty",
            model="demo-model",
            workspace=str(workspace),
        )

        api_main.persist_session_state(session)
        self.assertIsNone(api_main._session_store.load(session.session_id))

        session.history_messages.append({"id": "u1", "role": "user", "content": "你好"})
        api_main.persist_session_state(session)

        persisted = api_main._session_store.load(session.session_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.history_messages[0]["content"], "你好")

        api_main._session_store.delete(session.session_id)


if __name__ == "__main__":
    unittest.main()
