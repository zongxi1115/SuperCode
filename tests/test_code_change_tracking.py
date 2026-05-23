import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from agent.schema import AgentEvent, AgentResponse, ToolCall, ToolResult
from fastapi_app import main as api_main


class _FakeCodeChangeChatSession:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        target = self.workspace / "src" / "tracked.ts"
        target.parent.mkdir(parents=True, exist_ok=True)

        tool_call = ToolCall(
            id="tool-write-1",
            name="write_file",
            arguments={"filename": "src/tracked.ts", "content": "export const tracked = true;\n"},
        )
        if on_event is not None:
            on_event(AgentEvent(type="tool_call", step_index=1, tool_call=tool_call))
        target.write_text("export const tracked = true;\n", encoding="utf-8")
        if on_event is not None:
            on_event(
                AgentEvent(
                    type="tool_result",
                    step_index=1,
                    tool_call=tool_call,
                    tool_result=ToolResult(
                        name="write_file",
                        tool_call_id=tool_call.id,
                        output="已创建文件: src/tracked.ts",
                        success=True,
                    ),
                )
            )
        return AgentResponse(task=user_message, final_output="done")


class _FakeApplyPatchCodeChangeChatSession:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def ask(self, user_message: str, on_event=None) -> AgentResponse:
        target = self.workspace / "src" / "tracked.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const tracked = false;\n", encoding="utf-8")

        tool_call = ToolCall(
            id="tool-patch-1",
            name="apply_patch",
            arguments={
                "filename": "src/tracked.ts",
                "start_line": 1,
                "end_line": 1,
                "new_content": "export const tracked = true;",
            },
        )
        if on_event is not None:
            on_event(AgentEvent(type="tool_call", step_index=1, tool_call=tool_call))
        target.write_text("export const tracked = true;\n", encoding="utf-8")
        if on_event is not None:
            on_event(
                AgentEvent(
                    type="tool_result",
                    step_index=1,
                    tool_call=tool_call,
                    tool_result=ToolResult(
                        name="apply_patch",
                        tool_call_id=tool_call.id,
                        output={"summary": "已修改文件 src/tracked.ts 的第 1 到 1 行。", "files": ["src/tracked.ts"]},
                        success=True,
                    ),
                )
            )
        return AgentResponse(task=user_message, final_output="done")


class CodeChangeTrackingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for session_id in ["session-save", "session-delete", "session-stream-code-change", "session-stream-apply-patch"]:
            api_main._sessions.pop(session_id, None)
            api_main._session_store.delete(session_id)

    async def test_save_file_records_editor_code_change(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-save-code-change-")).resolve()
        target = workspace / "src" / "app.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("const value = 1;\n", encoding="utf-8")

        session = api_main.UISession(
            session_id="session-save",
            model="test-model",
            workspace=str(workspace),
        )
        api_main._sessions[session.session_id] = session

        response = await api_main.save_file(
            session_id=session.session_id,
            path="src/app.ts",
            body={"content": "const value = 2;\n"},
        )
        payload = json.loads(response.body.decode("utf-8"))

        self.assertTrue(payload["saved"])
        self.assertEqual(len(session.code_changes), 1)
        self.assertEqual(session.code_changes[0]["source"], "editor")
        self.assertEqual(session.code_changes[0]["action"], "modified")
        self.assertEqual(payload["codeChange"]["path"], "src/app.ts")

    async def test_confirm_delete_records_deleted_code_change(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-delete-code-change-")).resolve()
        target = workspace / "src" / "dead.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("export const dead = true;\n", encoding="utf-8")

        session = api_main.UISession(
            session_id="session-delete",
            model="test-model",
            workspace=str(workspace),
        )
        session.pending_delete_confirmations["delete-tool-1"] = {
            "filename": "src/dead.ts",
            "assistant_id": "assistant-1",
            "step_index": 3,
        }
        api_main._sessions[session.session_id] = session

        response = await api_main.confirm_delete_tool(
            session_id=session.session_id,
            tool_id="delete-tool-1",
            request=api_main.ToolConfirmationRequest(approved=True),
        )
        payload = json.loads(response.body.decode("utf-8"))

        self.assertTrue(payload["success"])
        self.assertEqual(len(session.code_changes), 1)
        self.assertEqual(session.code_changes[0]["action"], "deleted")
        self.assertEqual(session.code_changes[0]["stepIndex"], 3)
        self.assertEqual(payload["codeChange"]["path"], "src/dead.ts")
        self.assertFalse(target.exists())

    async def test_run_agent_stream_emits_realtime_code_change_event(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-code-change-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-code-change",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeCodeChangeChatSession(workspace),
        )
        api_main._sessions[session.session_id] = session
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        await api_main.run_agent_stream(session, "创建一个文件", queue)

        events: list[dict[str, object]] = []
        while True:
            item = await queue.get()
            if item is None:
                break
            events.append(item)

        self.assertEqual(len(session.code_changes), 1)
        self.assertEqual(session.code_changes[0]["action"], "added")
        code_change_event = next(event for event in events if event.get("type") == "data-code-change")
        payload = code_change_event.get("payload")
        assert isinstance(payload, dict)
        self.assertEqual(payload["data"]["path"], "src/tracked.ts")

    async def test_run_agent_stream_tracks_apply_patch_file_changes(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-stream-apply-patch-")).resolve()
        session = api_main.UISession(
            session_id="session-stream-apply-patch",
            model="test-model",
            workspace=str(workspace),
            chat_session=_FakeApplyPatchCodeChangeChatSession(workspace),
        )
        api_main._sessions[session.session_id] = session
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()

        await api_main.run_agent_stream(session, "修改一个文件", queue)

        self.assertEqual(len(session.code_changes), 1)
        self.assertEqual(session.code_changes[0]["action"], "modified")
        self.assertEqual(session.code_changes[0]["path"], "src/tracked.ts")


if __name__ == "__main__":
    unittest.main()
