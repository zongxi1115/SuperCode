import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.tools import ToolContext
from coding_agent.tools import ExcecuteTool, ExecuteTool


class ExecuteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-execute-"))
        self.context = ToolContext(workspace=self.workspace)

    def test_execute_requires_timeout(self) -> None:
        tool = ExecuteTool()

        with self.assertRaisesRegex(ValueError, "timeout 为必填参数"):
            tool.run({"content": "Get-Date"}, self.context)

    def test_execute_rejects_non_positive_timeout(self) -> None:
        tool = ExecuteTool()

        with self.assertRaisesRegex(ValueError, "timeout 必须大于 0"):
            tool.run({"content": "Get-Date", "timeout": 0}, self.context)

    def test_execute_passes_timeout_to_subprocess(self) -> None:
        tool = ExecuteTool()

        with patch("coding_agent.tools.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "ok\n"
            mock_run.return_value.stderr = ""
            mock_run.return_value.returncode = 0

            output = tool.run({"content": "Get-Date", "timeout": 7}, self.context)

        self.assertIn("exit_code: 0", output)
        self.assertIn("stdout:\nok", output)
        self.assertEqual(mock_run.call_args.kwargs["timeout"], 7)

    def test_excecute_tool_uses_same_timeout_contract(self) -> None:
        tool = ExcecuteTool()

        with self.assertRaisesRegex(ValueError, "timeout 为必填参数"):
            tool.run({"content": "Get-Date"}, self.context)


if __name__ == "__main__":
    unittest.main()
