import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent.schema import AgentEvent, AgentResponse, ToolCall, ToolResult
from fastapi_app import main as api_main


class _FakeStreamingChatSession:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        if on_event is not None:
            on_event(
                AgentEvent(
                    type="final_answer_delta",
                    step_index=1,
                    delta="部分回复",
                    final_answer="部分回复",
                )
            )
        self.started.set()
        self.release.wait(timeout=2)
        return AgentResponse(task=user_message, final_output="部分回复，最终完成")


class _FakeCompletedChatSession:
    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        if on_event is not None:
            on_event(
                AgentEvent(
                    type="final_answer_delta",
                    step_index=1,
                    delta="部分回复",
                    final_answer="部分回复",
                )
            )
        return AgentResponse(task=user_message, final_output="部分回复，最终完成")


class _FakeFailingChatSession:
    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        if on_event is not None:
            on_event(
                AgentEvent(
                    type="final_answer_delta",
                    step_index=1,
                    delta="部分回复",
                    final_answer="部分回复",
                )
            )
        raise RuntimeError("boom")


class _FakeTracedChatSession:
    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        if on_event is not None:
            on_event(AgentEvent(type="thought_delta", step_index=1, delta="先看 README"))
            on_event(AgentEvent(type="thought", step_index=1, thought="先看 README"))
            tool_call = ToolCall(id="step-1-tool-1-read_file", name="read_file", arguments={"filename": "README.md"})
            on_event(AgentEvent(type="tool_call", step_index=1, tool_call=tool_call))
            on_event(
                AgentEvent(
                    type="tool_result",
                    step_index=1,
                    tool_call=tool_call,
                    tool_result=ToolResult(
                        name="read_file",
                        tool_call_id=tool_call.id,
                        output="README content",
                        success=True,
                    ),
                )
            )
            on_event(
                AgentEvent(
                    type="final_answer_delta",
                    step_index=2,
                    delta="结论",
                    final_answer="结论",
                )
            )
        return AgentResponse(task=user_message, final_output="结论")


class StreamPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_does_not_apply_five_minute_backend_timeout(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-no-timeout-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-0",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeCompletedChatSession(),
        )
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        def unexpected_wait_for(*args, **kwargs):
            raise AssertionError("run_agent_stream 不应再包装 5 分钟 wait_for 超时")

        with mock.patch.object(api_main.asyncio, "wait_for", side_effect=unexpected_wait_for):
            await api_main.run_agent_stream(session, "你好", queue)

        self.assertEqual(len(session.history_messages), 2)
        self.assertEqual(session.history_messages[0]["role"], "user")
        self.assertEqual(session.history_messages[0]["content"], "你好")
        self.assertEqual(session.history_messages[1]["content"], "部分回复，最终完成")

    async def test_interrupted_stream_keeps_partial_assistant_message_in_history(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-")).resolve()
        fake_chat_session = _FakeStreamingChatSession()
        session = api_main.UISession(
            session_id="session-stream-1",
            model="test-model",
            workspace=str(workspace),
            chat_session=fake_chat_session,
        )
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        task = asyncio.create_task(api_main.run_agent_stream(session, "你好", queue))

        await asyncio.to_thread(fake_chat_session.started.wait, 1)
        task.cancel()
        fake_chat_session.release.set()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(len(session.history_messages), 2)
        self.assertEqual(session.history_messages[0]["role"], "user")
        self.assertEqual(session.history_messages[0]["content"], "你好")
        self.assertEqual(session.history_messages[1]["role"], "assistant")
        self.assertEqual(session.history_messages[1]["content"], "部分回复")

    async def test_completed_stream_updates_existing_assistant_message_instead_of_duplicating(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-complete-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-2",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeCompletedChatSession(),
        )
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        await api_main.run_agent_stream(session, "你好", queue)

        self.assertEqual(len(session.history_messages), 2)
        self.assertEqual(session.history_messages[1]["content"], "部分回复，最终完成")

    async def test_failed_stream_persists_partial_assistant_text_with_error(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-failure-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-3",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeFailingChatSession(),
        )
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        await api_main.run_agent_stream(session, "你好", queue)

        self.assertEqual(len(session.history_messages), 2)
        self.assertEqual(session.history_messages[0]["role"], "user")
        self.assertEqual(session.history_messages[1]["role"], "assistant")
        self.assertIn("部分回复", session.history_messages[1]["content"])
        self.assertIn("后端处理在流式阶段失败：boom", session.history_messages[1]["content"])

    async def test_completed_stream_persists_structured_parts_in_real_order(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-parts-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-4",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeTracedChatSession(),
        )
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        await api_main.run_agent_stream(session, "你好", queue)

        assistant_message = session.history_messages[1]
        parts = assistant_message.get("parts")

        self.assertIsInstance(parts, list)
        assert isinstance(parts, list)
        self.assertEqual([part.get("type") for part in parts], ["thinking", "tool_call", "text"])
        self.assertEqual(parts[0].get("text"), "先看 README")
        self.assertEqual(parts[1].get("toolCall", {}).get("name"), "read_file")
        self.assertEqual(parts[2].get("text"), "结论")


if __name__ == "__main__":
    unittest.main()
