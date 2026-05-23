import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.schema import AgentResponse, StepRecord, ToolCall
from fastapi_app import main as api_main


class _FakeCodingSubAgent:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, D401
        self.args = args
        self.kwargs = kwargs

    def run_turn(self, state, on_event=None, continue_existing_turn=False):  # noqa: ANN001
        return AgentResponse(
            task=state.current_input,
            final_output="子任务完成",
            steps=[
                StepRecord(
                    turn_index=1,
                    index=1,
                    thought="先改文件",
                    tool_call=ToolCall(
                        id="tool-1",
                        name="write_file",
                        arguments={"filename": "deploy/config.yml", "content": "name: demo"},
                    ),
                ),
                StepRecord(
                    turn_index=1,
                    index=2,
                    thought="再跑检查",
                    tool_call=ToolCall(
                        id="tool-2",
                        name="execute",
                        arguments={"content": "python -m pytest tests/test_config.py", "timeout": 20},
                    ),
                ),
            ],
        )


class SubagentDispatchTests(unittest.TestCase):
    def test_dispatch_subagent_task_returns_changed_files_and_commands(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-subagent-")).resolve()
        session = api_main.UISession(
            session_id="subagent-session",
            model="Demo",
            workspace=str(workspace),
            agent_type="deploy",
            env_file="env::.env",
        )
        dummy_config = SimpleNamespace(include_thoughts_in_context=False)

        with (
            patch.object(api_main, "build_agent_config", return_value=(dummy_config, "env::.env")),
            patch.object(api_main, "OpenAICompatibleClient", return_value=object()),
            patch.object(api_main, "CodingPromptBrain", return_value=object()),
            patch.object(api_main, "CodingAgent", _FakeCodingSubAgent),
        ):
            output = api_main.dispatch_subagent_task(session, "coding", "修改部署配置")

        self.assertEqual(output["agent_type"], "coding")
        self.assertEqual(output["status"], "completed")
        self.assertEqual(output["final_output"], "子任务完成")
        self.assertEqual(output["changed_files"], ["deploy/config.yml"])
        self.assertEqual(output["commands_run"], ["python -m pytest tests/test_config.py"])
        self.assertIn("write_file", output["tool_names"])
        self.assertIn("execute", output["tool_names"])

    def test_dispatch_subagent_task_emits_streaming_snapshots(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-subagent-stream-")).resolve()
        session = api_main.UISession(
            session_id="subagent-session-stream",
            model="Demo",
            workspace=str(workspace),
            agent_type="deploy",
            env_file="env::.env",
        )
        dummy_config = SimpleNamespace(include_thoughts_in_context=False)
        emitted: list[tuple[str, dict[str, object]]] = []

        with (
            patch.object(api_main, "build_agent_config", return_value=(dummy_config, "env::.env")),
            patch.object(api_main, "OpenAICompatibleClient", return_value=object()),
            patch.object(api_main, "CodingPromptBrain", return_value=object()),
            patch.object(api_main, "CodingAgent", _FakeCodingSubAgent),
        ):
            api_main.dispatch_subagent_task(
                session,
                "coding",
                "修改部署配置",
                {
                    "runtime_event_emitter": lambda event_type, payload: emitted.append((event_type, payload)),
                    "tool_call_id": "delegate-tool-1",
                },
            )

        self.assertGreaterEqual(len(emitted), 2)
        self.assertEqual(emitted[0][0], "data-subagent-state")
        self.assertEqual(emitted[0][1]["toolCallId"], "delegate-tool-1")
        self.assertEqual(emitted[-1][1]["status"], "completed")
        self.assertEqual(emitted[-1][1]["changedFiles"], ["deploy/config.yml"])


if __name__ == "__main__":
    unittest.main()
