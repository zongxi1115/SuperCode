import tempfile
import unittest
from pathlib import Path

from agent.schema import AgentResponse, StepRecord, ToolCall
from agent.tools import ToolContext
from coding_agent.tools import DelegateCodeExplorationTool
from fastapi_app.ui_message_stream import UIMessageStreamAdapter


class _FakeCodeExplorationSubAgent:
    def __init__(self) -> None:
        self.received_input = ""

    def run_turn(self, state, on_event=None, continue_existing_turn=False):  # noqa: ANN001
        del on_event, continue_existing_turn
        self.received_input = state.current_input
        return AgentResponse(
            task=state.current_input,
            final_output=(
                "## 相关区域\n"
                "- fastapi_app/main.py 负责会话流。\n"
                "- frontend/src/App.tsx 负责 SSE 消费。\n"
                "## 建议下一步\n"
                "- tests/test_ui_message_stream.py\n"
            ),
            steps=[
                StepRecord(
                    turn_index=1,
                    index=1,
                    thought="先定位消息流",
                    tool_call=ToolCall(
                        id="tool-1",
                        name="grep_file",
                        arguments={
                            "regex": "data-subagent",
                            "search_path": ".",
                            "output_mode": "files_with_matches",
                        },
                    ),
                ),
                StepRecord(
                    turn_index=1,
                    index=2,
                    thought="再读关键文件",
                    tool_call=ToolCall(
                        id="tool-2",
                        name="read_file",
                        arguments={"filename": "fastapi_app/main.py", "offset": 0, "limit": 80},
                    ),
                ),
            ],
        )


class DelegateCodeExplorationToolTests(unittest.TestCase):
    def test_delegate_code_exploration_returns_read_only_snapshot(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-subagent-")).resolve()
        fake_subagent = _FakeCodeExplorationSubAgent()
        emitted: list[tuple[str, dict[str, object]]] = []
        tool = DelegateCodeExplorationTool()

        output = tool.run(
            {
                "task": "检查 subagent 消息流",
                "focus_paths": ["fastapi_app", "frontend/src"],
                "max_steps": 4,
            },
            ToolContext(
                workspace=workspace,
                metadata={
                    "code_exploration_subagent_factory": lambda _context, _max_steps: fake_subagent,
                    "runtime_event_emitter": lambda event_type, payload: emitted.append((event_type, payload)),
                },
            ),
        )

        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["files_read"], ["fastapi_app/main.py"])
        self.assertEqual(output["commands_run"], [])
        self.assertEqual(output["recommended_files"][:2], ["fastapi_app/main.py", "frontend/src/App.tsx"])
        self.assertIn("fastapi_app", fake_subagent.received_input)

        data_part = output["data_part"]
        self.assertEqual(data_part["type"], "data-subagent-task")
        snapshot = data_part["data"]
        self.assertEqual(snapshot["kind"], "code_exploration")
        self.assertEqual(snapshot["title"], "代码探索")
        self.assertEqual(snapshot["changedFiles"], [])
        self.assertEqual(snapshot["filesRead"], ["fastapi_app/main.py"])
        self.assertIn("grep_file", snapshot["toolNames"])

        self.assertGreaterEqual(len(emitted), 2)
        self.assertEqual(emitted[0][0], "data-subagent-task")
        self.assertEqual(emitted[0][1]["data"]["status"], "running")
        self.assertEqual(emitted[-1][1]["data"]["status"], "completed")

    def test_ui_message_adapter_forwards_subagent_data_part(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = adapter.convert(
            {
                "type": "tool_result",
                "payload": {
                    "assistant_id": "m_1",
                    "id": "delegate-1",
                    "name": "delegate_code_exploration",
                    "output": {
                        "data_part": {
                            "type": "data-subagent-task",
                            "data": {
                                "kind": "code_exploration",
                                "title": "代码探索",
                                "status": "completed",
                                "task": "检查消息流",
                                "steps": [],
                                "stepCount": 0,
                                "filesRead": ["fastapi_app/main.py"],
                                "changedFiles": [],
                                "commandsRun": [],
                                "findings": ["发现已有 data-* 通道"],
                                "recommendedFiles": ["tests/test_ui_message_stream.py"],
                            },
                        }
                    },
                    "success": True,
                },
            }
        )

        subagent_part = next(part for part in parts if part["type"] == "data-subagent-task")
        self.assertEqual(subagent_part["data"]["kind"], "code_exploration")
        self.assertEqual(subagent_part["data"]["filesRead"], ["fastapi_app/main.py"])


if __name__ == "__main__":
    unittest.main()
