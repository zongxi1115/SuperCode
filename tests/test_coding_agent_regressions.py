import tempfile
import unittest
from pathlib import Path

from agent.agent import CodingAgent
from agent.brain import BrainDecision
from agent.schema import AgentState, StepRecord
from agent.tools import BaseTool, ToolContext
from coding_agent.brain import CodingPromptBrain
from coding_agent.tools import ReadFileTool


class CodingPromptBrainMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brain = CodingPromptBrain(client=object())
        self.state = AgentState(task="task", current_input="继续")
        self.state.data["turn_index"] = 1
        self.state.data["step_records"] = [
            StepRecord(turn_index=1, index=1, thought="先读文件", final_answer=None)
        ]

    def test_native_continuation_instruction_avoids_json_protocol(self) -> None:
        messages = self.brain._build_messages(
            self.state,
            tool_definitions={},
            response_mode="native_tools",
        )

        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("直接使用原生 tool calling", messages[-1]["content"])
        self.assertNotIn("继续输出下一步决策 JSON", messages[-1]["content"])

    def test_legacy_continuation_instruction_keeps_json_protocol(self) -> None:
        messages = self.brain._build_messages(
            self.state,
            tool_definitions={},
            response_mode="legacy_json",
        )

        self.assertIn("继续输出下一步决策 JSON", messages[-1]["content"])

    def test_current_turn_history_includes_planning_thoughts_by_default(self) -> None:
        messages = self.brain._build_messages(
            self.state,
            tool_definitions={},
            response_mode="native_tools",
        )

        history_message = messages[-2]["content"]
        self.assertIn("思考：先读文件", history_message)

    def test_current_turn_history_keeps_planning_thoughts_when_enabled(self) -> None:
        self.state.data["include_thoughts_in_context"] = True

        messages = self.brain._build_messages(
            self.state,
            tool_definitions={},
            response_mode="native_tools",
        )

        history_message = messages[-2]["content"]
        self.assertIn("思考：先读文件", history_message)


class ReadFileToolMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-read-file-"))
        self.context = ToolContext(workspace=self.workspace)
        self.tool = ReadFileTool()

    def test_read_file_includes_total_lines_and_eof_metadata(self) -> None:
        target = self.workspace / "demo.txt"
        target.write_text("a\nb\nc\nd\n", encoding="utf-8")

        output = self.tool.run(
            {"filename": "demo.txt", "start_line": 2, "end_line": 3},
            self.context,
        )

        self.assertIn("# Requested lines: 2-3", output)
        self.assertIn("# Actual lines: 2-3", output)
        self.assertIn("# Total lines: 4", output)
        self.assertIn("# EOF: false", output)
        self.assertIn("2 | b", output)
        self.assertIn("3 | c", output)

    def test_read_file_marks_eof_when_range_reaches_file_end(self) -> None:
        target = self.workspace / "demo.txt"
        target.write_text("a\nb\nc\n", encoding="utf-8")

        output = self.tool.run(
            {"filename": "demo.txt", "start_line": 3, "end_line": 10},
            self.context,
        )

        self.assertIn("# Requested lines: 3-10", output)
        self.assertIn("# Actual lines: 3-3", output)
        self.assertIn("# Total lines: 3", output)
        self.assertIn("# EOF: true", output)
        self.assertIn("3 | c", output)

    def test_read_file_reports_when_requested_range_starts_beyond_eof(self) -> None:
        target = self.workspace / "demo.txt"
        target.write_text("a\nb\n", encoding="utf-8")

        output = self.tool.run(
            {"filename": "demo.txt", "start_line": 5, "end_line": 8},
            self.context,
        )

        self.assertIn("# Requested lines: 5-8", output)
        self.assertIn("# Actual lines: 3-2", output)
        self.assertIn("# Total lines: 2", output)
        self.assertIn("# EOF: true", output)
        self.assertIn("# Note: requested range starts beyond end of file.", output)


class _ConfirmationTool(BaseTool):
    name = "git_commit"
    description = "需要确认的测试工具"

    def run(self, arguments, context):  # noqa: ANN001
        return {
            "requires_confirmation": True,
            "message": "确认提交？",
            "commit_message": "test commit",
        }


class _NoopTool(BaseTool):
    name = "git_commit"
    description = "普通测试工具"

    def run(self, arguments, context):  # noqa: ANN001
        return {
            "ok": True,
            "arguments": arguments,
        }


class _UserInputTool(BaseTool):
    name = "connect"
    description = "需要用户填写信息的测试工具"

    def run(self, arguments, context):  # noqa: ANN001
        return {
            "requires_user_input": True,
            "input_kind": "deploy_connect",
            "fields": [{"name": "root_path", "required": True}],
        }


class _StopAfterConfirmationBrain:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state, tool_definitions, on_stream=None):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return BrainDecision.call_tool(
                thought="先发起提交确认",
                tool_name="git_commit",
                tool_arguments={"message": "test commit"},
            )
        return BrainDecision.finish(
            thought="如果还能走到这里，说明没有暂停",
            final_answer="unexpected",
        )


class _DelayedFinishBrain:
    def __init__(self, final_on_call: int) -> None:
        self.calls = 0
        self.final_on_call = final_on_call

    def decide(self, state, tool_definitions, on_stream=None):  # noqa: ANN001
        self.calls += 1
        if self.calls >= self.final_on_call:
            return BrainDecision.finish(
                thought="步数足够了，直接收尾",
                final_answer="done",
            )
        return BrainDecision.call_tool(
            thought=f"继续第 {self.calls} 次占位调用",
            tool_name="git_commit",
            tool_arguments={"message": f"round-{self.calls}"},
        )


class _StopAfterUserInputBrain:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, state, tool_definitions, on_stream=None):  # noqa: ANN001
        self.calls += 1
        if self.calls == 1:
            return BrainDecision.call_tool(
                thought="先发起 connect",
                tool_name="connect",
                tool_arguments={},
            )
        return BrainDecision.finish(
            thought="如果还能走到这里，说明没有暂停",
            final_answer="unexpected",
        )


class HumanInLoopPauseTests(unittest.TestCase):
    def test_agent_pauses_turn_when_tool_requires_confirmation(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-confirmation-"))
        agent = CodingAgent(
            brain=_StopAfterConfirmationBrain(),
            tools=[_ConfirmationTool()],
            workspace=workspace,
            max_steps=3,
        )

        response = agent.run("帮我提交")

        self.assertEqual(len(response.steps), 1)
        self.assertEqual(response.final_output, "")
        self.assertEqual(response.steps[0].tool_results[0].output["requires_confirmation"], True)

    def test_agent_pauses_turn_when_tool_requires_user_input(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-user-input-"))
        agent = CodingAgent(
            brain=_StopAfterUserInputBrain(),
            tools=[_UserInputTool()],
            workspace=workspace,
            max_steps=3,
        )

        response = agent.run("帮我连接部署目标")

        self.assertEqual(len(response.steps), 1)
        self.assertEqual(response.final_output, "")
        self.assertEqual(response.steps[0].tool_results[0].output["requires_user_input"], True)

    def test_continue_existing_turn_continues_step_index(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-confirmation-"))
        agent = CodingAgent(
            brain=_StopAfterConfirmationBrain(),
            tools=[_ConfirmationTool()],
            workspace=workspace,
            max_steps=3,
        )
        state = AgentState(task="task", current_input="帮我提交")

        paused_response = agent.run_turn(state)
        continued_response = agent.run_turn(state, continue_existing_turn=True)

        self.assertEqual(paused_response.steps[0].index, 1)
        self.assertEqual(continued_response.steps[0].index, 2)


class MaxStepsCompatibilityTests(unittest.TestCase):
    def test_agent_default_step_budget_allows_longer_tasks(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-max-steps-"))
        agent = CodingAgent(
            brain=_DelayedFinishBrain(final_on_call=5),
            tools=[_NoopTool()],
            workspace=workspace,
        )

        response = agent.run("继续执行直到完成")

        self.assertEqual(response.final_output, "done")
        self.assertEqual(len(response.steps), 5)
        self.assertEqual(response.steps[-1].final_answer, "done")

    def test_agent_honors_explicit_step_budget_as_safety_guard(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-max-steps-"))
        agent = CodingAgent(
            brain=_DelayedFinishBrain(final_on_call=5),
            tools=[_NoopTool()],
            workspace=workspace,
            max_steps=2,
        )

        response = agent.run("继续执行直到完成")

        self.assertIn("仍未收敛", response.final_output)
        self.assertEqual(len(response.steps), 3)
        self.assertEqual(response.steps[-1].final_answer, response.final_output)


if __name__ == "__main__":
    unittest.main()
