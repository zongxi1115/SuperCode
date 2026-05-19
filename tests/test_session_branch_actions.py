import tempfile
import unittest
import uuid
from pathlib import Path

from agent import ChatSession
from fastapi_app import main as api_main


class SessionBranchActionsTests(unittest.TestCase):
    def _make_session(self) -> api_main.UISession:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-session-branch-")).resolve()
        session = api_main.UISession(
            session_id=f"session-{uuid.uuid4().hex}",
            model="demo-model",
            workspace=str(workspace),
            chat_session=ChatSession(agent=object()),
            mode="agent",
            agent_type="coding",
        )
        session.selected_file_path = "fastapi_app/main.py"
        session.open_files = ["fastapi_app/main.py", "frontend/src/App.tsx"]
        session.history_messages = [
            {"id": "u1", "role": "user", "content": "实现会话压缩"},
            {
                "id": "a1",
                "role": "assistant",
                "content": "先补后端压缩接口",
                "thoughts": "先做独立接口，别破坏现有聊天流。",
                "toolCalls": [
                    {"id": "tool-1", "name": "read_file", "state": "completed"},
                ],
            },
            {"id": "u2", "role": "user", "content": "再把前端按钮接上"},
            {
                "id": "a2",
                "role": "assistant",
                "content": "再补前端动作",
                "thoughts": "前端要支持 copy/compress/fork/restore。",
                "toolCalls": [
                    {"id": "tool-2", "name": "apply_patch", "state": "completed"},
                ],
            },
        ]
        session.history_tools = [
            {
                "id": "tool-1",
                "name": "read_file",
                "arguments": {"filename": "fastapi_app/main.py"},
                "output": "context endpoint",
                "success": True,
                "state": "completed",
            },
            {
                "id": "tool-2",
                "name": "apply_patch",
                "arguments": {"path": "frontend/src/components/app/chat-panel.tsx"},
                "output": "patched",
                "success": True,
                "state": "completed",
            },
        ]
        session.thoughts = [
            "先做独立接口，别破坏现有聊天流。",
            "前端要支持 copy/compress/fork/restore。",
        ]
        session.code_changes = [
            {
                "id": "change-1",
                "action": "modified",
                "path": "fastapi_app/main.py",
                "assistantId": "a1",
                "toolCallId": "tool-1",
                "timestamp": 1,
                "linesAdded": 5,
                "linesDeleted": 0,
                "summary": "新增压缩接口",
                "diffPreview": "@@",
            },
            {
                "id": "change-2",
                "action": "modified",
                "path": "frontend/src/components/app/chat-panel.tsx",
                "assistantId": "a2",
                "toolCallId": "tool-2",
                "timestamp": 2,
                "linesAdded": 8,
                "linesDeleted": 1,
                "summary": "接入操作按钮",
                "diffPreview": "@@",
            },
        ]
        api_main.seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        self.addCleanup(api_main._session_store.delete, session.session_id)
        self.addCleanup(api_main._sessions.pop, session.session_id, None)
        return session

    def test_fork_session_from_current_clones_history_into_new_session(self) -> None:
        session = self._make_session()

        forked = api_main.fork_session_from_current(session)
        self.addCleanup(api_main._session_store.delete, forked.session_id)
        self.addCleanup(api_main._sessions.pop, forked.session_id, None)

        self.assertNotEqual(forked.session_id, session.session_id)
        self.assertEqual(forked.workspace, session.workspace)
        self.assertEqual(forked.history_messages, session.history_messages)
        self.assertEqual(forked.history_tools, session.history_tools)
        self.assertEqual(forked.code_changes, session.code_changes)
        self.assertIsNot(forked.history_messages, session.history_messages)
        self.assertIsNotNone(api_main._session_store.load(forked.session_id))

    def test_restore_session_to_message_truncates_later_history(self) -> None:
        session = self._make_session()

        snapshot = api_main.restore_session_to_message(session, "a1")

        self.assertEqual(snapshot.sessionId, session.session_id)
        self.assertEqual([message["id"] for message in session.history_messages], ["u1", "a1"])
        self.assertEqual([tool["id"] for tool in session.history_tools], ["tool-1"])
        self.assertEqual([change["id"] for change in session.code_changes], ["change-1"])
        self.assertEqual(session.thoughts, ["先做独立接口，别破坏现有聊天流。"])
        self.assertEqual(
            [(message.role, message.content) for message in session.chat_session.state.conversation_messages],
            [("user", "实现会话压缩"), ("assistant", "先补后端压缩接口")],
        )


if __name__ == "__main__":
    unittest.main()
