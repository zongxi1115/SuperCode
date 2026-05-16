import tempfile
import time
import unittest
from pathlib import Path

from agent.agent import CodingAgent
from agent.schema import ToolCall
from agent.tools import BaseTool, ToolContext


class _DelayedTool(BaseTool):
    description = "test"
    supports_parallel = True

    def __init__(self, name: str, delay: float) -> None:
        self.name = name
        self.delay = delay

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        time.sleep(self.delay)
        return self.name


class ParallelToolStreamingTests(unittest.TestCase):
    def test_parallel_tool_results_are_reported_as_completed(self) -> None:
        fast_tool = _DelayedTool("fast", 0.01)
        slow_tool = _DelayedTool("slow", 0.15)
        agent = CodingAgent(
            brain=object(),  # type: ignore[arg-type]
            tools=[fast_tool, slow_tool],
            workspace=Path(tempfile.mkdtemp(prefix="supercode-agent-")),
        )
        context = ToolContext(workspace=Path(agent.workspace))
        reported_order: list[str] = []

        agent._execute_tool_calls(
            [
                ToolCall(id="slow", name="slow", arguments={}),
                ToolCall(id="fast", name="fast", arguments={}),
            ],
            context,
            on_result=lambda tool_call, result: reported_order.append(tool_call.name),
        )

        self.assertEqual(reported_order, ["fast", "slow"])


if __name__ == "__main__":
    unittest.main()
