import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent.schema import AgentEvent, AgentResponse
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

        self.assertEqual(len(session.history_messages), 1)
        self.assertEqual(session.history_messages[0]["content"], "部分回复，最终完成")

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

        self.assertEqual(len(session.history_messages), 1)
        self.assertEqual(session.history_messages[0]["role"], "assistant")
        self.assertEqual(session.history_messages[0]["content"], "部分回复")

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

        self.assertEqual(len(session.history_messages), 1)
        self.assertEqual(session.history_messages[0]["content"], "部分回复，最终完成")


if __name__ == "__main__":
    unittest.main()
