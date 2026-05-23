import tempfile
import unittest
import uuid
from pathlib import Path

from agent import ChatSession
from fastapi_app import main as api_main
from fastapi_app.api_models import SessionContextCompressionRequest


class ContextCompressionTests(unittest.TestCase):
    def _make_session(self) -> api_main.UISession:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-context-compress-")).resolve()
        session = api_main.UISession(
            session_id=f"session-{uuid.uuid4().hex}",
            model="demo-model",
            workspace=str(workspace),
            chat_session=ChatSession(agent=object()),
            mode="agent",
            agent_type="coding",
        )
        session.selected_file_path = "frontend/src/components/app/chat-panel.tsx"
        session.open_files = [
            "frontend/src/components/app/chat-panel.tsx",
            "fastapi_app/main.py",
            "fastapi_app/api_models.py",
        ]
        session.history_messages = [
            {"id": "u1", "role": "user", "content": "后端做一个压缩上下文的接口"},
            {"id": "a1", "role": "assistant", "content": "先看一下现有 session 和 context 接口结构"},
            {"id": "u2", "role": "user", "content": "接口最好支持 preview 和 apply"},
            {
                "id": "a2",
                "role": "assistant",
                "content": "可以，我会保留最近消息并把旧上下文压成摘要",
                "thoughts": "优先不要破坏现有 chat stream，尽量做成独立接口。",
            },
            {"id": "u3", "role": "user", "content": "还要考虑前端后续接按钮"},
        ]
        session.history_tools = [
            {
                "id": "tool-1",
                "name": "read_file",
                "arguments": {"filename": "fastapi_app/main.py"},
                "output": "def get_session_context(...",
                "success": True,
                "state": "completed",
            },
            {
                "id": "tool-2",
                "name": "grep",
                "arguments": {"regex": "context"},
                "output": "frontend/src/components/app/chat-panel.tsx: 压缩会话",
                "success": True,
                "state": "completed",
            },
            {
                "id": "tool-3",
                "name": "read_file",
                "arguments": {"filename": "frontend/src/components/app/chat-panel.tsx"},
                "output": "disabled={action.key === \"compress\"}",
                "success": True,
                "state": "completed",
            },
        ]
        session.thoughts = [
            "先确认后端已有 session context 快照，避免重复造轮子。",
            "apply 模式需要真正改写历史消息和工具记录。",
            "前端已经有压缩按钮占位，接口设计最好直接可接。",
        ]
        session.code_changes = [
            {
                "id": "change-1",
                "action": "modified",
                "path": "fastapi_app/main.py",
                "timestamp": 1,
                "linesAdded": 12,
                "linesDeleted": 0,
                "summary": "新增 context 压缩接口的主逻辑",
                "diffPreview": "@@",
            }
        ]
        session.plan_steps = [
            {
                "id": "1",
                "title": "补 API 模型",
                "description": "增加压缩上下文请求/响应定义",
                "status": "completed",
            },
            {
                "id": "2",
                "title": "实现后端压缩逻辑",
                "description": "支持 preview/apply 两种模式",
                "status": "running",
            },
            {
                "id": "3",
                "title": "补测试",
                "description": "覆盖 preview 和 apply",
                "status": "pending",
            },
        ]
        self.addCleanup(api_main._session_store.delete, session.session_id)
        return session

    def test_preview_compresses_context_without_mutating_session(self) -> None:
        session = self._make_session()
        original_message_count = len(session.history_messages)
        original_tool_count = len(session.history_tools)
        original_thought_count = len(session.thoughts)

        response = api_main.compress_session_context(
            session,
            SessionContextCompressionRequest(
                mode="preview",
                usageThreshold=0,
                preserveRecentMessages=2,
                preserveRecentTools=1,
                preserveRecentThoughts=1,
            ),
            summarizer=lambda _session, _source, _instruction: "## 目标\n实现压缩接口\n\n## 待继续\n补路由和测试",
        )

        self.assertFalse(response.applied)
        self.assertEqual(response.sourceMessageCount, 3)
        self.assertEqual(response.sourceToolCount, 2)
        self.assertEqual(response.sourceThoughtCount, 2)
        self.assertEqual(len(session.history_messages), original_message_count)
        self.assertEqual(len(session.history_tools), original_tool_count)
        self.assertEqual(len(session.thoughts), original_thought_count)
        self.assertGreater(response.savedEstimatedTokens, 0)
        self.assertIn("实现压缩接口", response.summary)
        self.assertIsNone(response.updatedContext)

    def test_apply_rewrites_history_and_reseeds_chat_session(self) -> None:
        session = self._make_session()

        response = api_main.compress_session_context(
            session,
            SessionContextCompressionRequest(
                mode="apply",
                usageThreshold=0,
                preserveRecentMessages=2,
                preserveRecentTools=1,
                preserveRecentThoughts=1,
            ),
            summarizer=lambda _session, _source, _instruction: "## 目标\n实现压缩接口\n\n## 关键上下文\n保留 preview/apply 两种模式",
        )

        self.assertTrue(response.applied)
        self.assertEqual(len(session.history_messages), 3)
        self.assertTrue(
            session.history_messages[0]["content"].startswith(api_main.CONTEXT_COMPRESSION_SUMMARY_PREFIX)
        )
        self.assertEqual(len(session.history_tools), 1)
        self.assertEqual(len(session.thoughts), 1)
        self.assertIsNotNone(response.updatedContext)
        assert response.updatedContext is not None
        self.assertEqual(response.updatedContext.messageCount, 3)
        self.assertEqual(response.updatedContext.toolCallCount, 1)
        self.assertEqual(response.updatedContext.thoughtCount, 1)

        conversation_messages = session.chat_session.state.conversation_messages
        self.assertEqual(len(conversation_messages), 3)
        self.assertEqual(conversation_messages[0].content, session.history_messages[0]["content"])
        self.assertEqual(
            session.chat_session.state.data["runtime_state"]["workspace"],
            session.workspace,
        )

    def test_preview_skips_compression_when_usage_below_threshold(self) -> None:
        session = self._make_session()

        response = api_main.compress_session_context(
            session,
            SessionContextCompressionRequest(
                mode="preview",
                usageThreshold=0.95,
            ),
            summarizer=lambda _session, _source, _instruction: "should not be used",
        )

        self.assertFalse(response.applied)
        self.assertEqual(response.summary, "")
        self.assertEqual(response.skippedReason, "usage_below_threshold")
        self.assertLess(response.usageRatio, response.usageThreshold)

    def test_context_snapshot_prefers_backend_usage_when_available(self) -> None:
        session = self._make_session()
        session.token_usage = {
            "inputTokens": 4321,
            "outputTokens": 210,
            "reasoningTokens": 64,
            "cachedInputTokens": 120,
            "totalTokens": 4595,
        }
        session.cumulative_token_usage = {
            "inputTokens": 9600,
            "outputTokens": 1800,
            "reasoningTokens": 320,
            "cachedInputTokens": 1500,
            "totalTokens": 11720,
        }
        session.max_context_tokens = 128000

        snapshot = session.context_snapshot()

        self.assertEqual(snapshot.estimatedTokens, 4321)
        self.assertEqual(snapshot.maxTokens, 128000)
        self.assertEqual(snapshot.usage.inputTokens, 4321)
        self.assertEqual(snapshot.usage.reasoningTokens, 64)
        self.assertEqual(snapshot.cumulativeUsage.totalTokens, 11720)


if __name__ == "__main__":
    unittest.main()
