import tempfile
import unittest
from pathlib import Path

from fastapi_app import main as api_main
from fastapi_app.app_config import STATE_DB_PATH
from fastapi_app.session_store import PersistedSessionState, SQLiteSessionStore
from fastapi_app.storage import SESSION_STORE


class SessionStoreTests(unittest.TestCase):
    def test_storage_uses_pytest_specific_state_db_path_under_test(self) -> None:
        self.assertIn("pytest", str(STATE_DB_PATH).lower())
        self.assertNotIn("D:\\vibe_projs\\SuperCode\\.supercode\\state.sqlite3".lower(), str(STATE_DB_PATH).lower())

    def test_sqlite_store_round_trips_session_state(self) -> None:
        db_path = Path(tempfile.mkdtemp(prefix="supercode-session-store-")) / "state.sqlite3"
        store = SQLiteSessionStore(db_path)
        state = PersistedSessionState(
            session_id="session-1",
            workspace="D:/demo",
            mode="agent",
            model="demo-model",
            reasoning_effort="high",
            agent_type="deploy",
            phase="connected",
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
            token_usage={
                "inputTokens": 1200,
                "outputTokens": 260,
                "reasoningTokens": 80,
                "cachedInputTokens": 300,
                "totalTokens": 1460,
            },
            cumulative_token_usage={
                "inputTokens": 3600,
                "outputTokens": 940,
                "reasoningTokens": 220,
                "cachedInputTokens": 900,
                "totalTokens": 4760,
            },
            max_context_tokens=128000,
            code_changes=[
                {
                    "id": "change-1",
                    "action": "modified",
                    "path": "src/app.tsx",
                    "timestamp": 300,
                    "linesAdded": 4,
                    "linesDeleted": 1,
                    "summary": "修改 src/app.tsx",
                    "diffPreview": "@@",
                }
            ],
            plan_steps=[{"id": "1", "title": "done", "status": "completed"}],
            plan_state={
                "status": "draft_ready",
                "draft": {
                    "title": "后台计划",
                    "summary": "做一个后台",
                    "markdown": "## todo\n- login",
                },
            },
            pending_user_input_requests={
                "tool-plan-1": {
                    "assistant_id": "a1",
                    "tool_name": "ask_plan_questions",
                }
            },
            pending_connect_requests={"tool-1": {"assistant_id": "a1"}},
            deploy_connections={
                "deploy-1": {
                    "session_id": "deploy-1",
                    "root_path": "D:/demo/app",
                    "display_name": "prod",
                    "description": "test",
                    "created_at": 123,
                }
            },
            deploy_state={
                "active_session_id": "deploy-1",
                "active_root_path": "D:/demo/app",
                "active_display_name": "prod",
                "pending_tool_id": None,
                "pending_tool_name": None,
                "pending_input_kind": None,
                "last_tool_name": "connect",
                "last_tool_state": "completed",
                "last_command": None,
                "last_command_cwd": None,
                "last_exit_code": None,
                "last_error": None,
                "last_message": "connected",
                "connection_count": 1,
                "known_session_ids": ["deploy-1"],
            },
        )

        store.save(state)
        loaded = store.load("session-1")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.agent_type, "deploy")
        self.assertEqual(loaded.reasoning_effort, "high")
        self.assertEqual(loaded.phase, "connected")
        self.assertEqual(loaded.history_messages[1]["content"], "收到")
        self.assertEqual(loaded.history_tools[0]["name"], "read_file")
        self.assertEqual(loaded.token_usage["inputTokens"], 1200)
        self.assertEqual(loaded.cumulative_token_usage["totalTokens"], 4760)
        self.assertEqual(loaded.max_context_tokens, 128000)
        self.assertEqual(loaded.code_changes[0]["path"], "src/app.tsx")
        self.assertEqual(loaded.plan_state["draft"]["title"], "后台计划")
        self.assertEqual(loaded.pending_user_input_requests["tool-plan-1"]["tool_name"], "ask_plan_questions")
        self.assertEqual(loaded.deploy_connections["deploy-1"]["display_name"], "prod")
        self.assertEqual(loaded.deploy_state["active_session_id"], "deploy-1")
        self.assertEqual(store.list()[0].session_id, "session-1")

        store.delete("session-1")

        self.assertIsNone(store.load("session-1"))

    def test_empty_new_session_is_not_persisted_until_it_has_interaction(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-empty-session-")).resolve()
        session = api_main.SESSION_REGISTRY.session_factory(
            session_id="session-empty",
            model="demo-model",
            workspace=str(workspace),
        )

        api_main.SESSION_REGISTRY.persist_session_state(session)
        self.assertIsNone(SESSION_STORE.load(session.session_id))

        session.history_messages.append({"id": "u1", "role": "user", "content": "你好"})
        api_main.SESSION_REGISTRY.persist_session_state(session)

        persisted = SESSION_STORE.load(session.session_id)
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(persisted.history_messages[0]["content"], "你好")

        SESSION_STORE.delete(session.session_id)


if __name__ == "__main__":
    unittest.main()
