import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.tools import ToolContext
from coding_agent.tools import (
    ExcecuteTool,
    ExecuteTool,
    InteractiveCommandSession,
    TerminalInputTool,
    TerminalWaitTool,
)


class ExecuteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-execute-"))
        self.context = ToolContext(workspace=self.workspace)
        self.interactive_session: InteractiveCommandSession | None = None

    def tearDown(self) -> None:
        if self.interactive_session is not None:
            self.interactive_session.close()

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

        with patch("coding_agent.tools.subprocess.Popen") as mock_popen:
            process = mock_popen.return_value
            process.communicate.return_value = ("ok\n", "")
            process.returncode = 0

            output = tool.run({"content": "Get-Date", "timeout": 7}, self.context)

        self.assertIn("exit_code: 0", output)
        self.assertIn("stdout:\nok", output)
        self.assertEqual(process.communicate.call_args.kwargs["timeout"], 7)

    def test_execute_kills_process_tree_on_timeout(self) -> None:
        tool = ExecuteTool()

        with (
            patch("coding_agent.tools.subprocess.Popen") as mock_popen,
            patch("coding_agent.tools.subprocess.run") as mock_run,
            patch("coding_agent.tools.sys.platform", "win32"),
        ):
            process = mock_popen.return_value
            process.pid = 4321
            process.poll.return_value = None
            process.communicate.side_effect = [
                subprocess.TimeoutExpired(cmd="powershell", timeout=2),
                ("", ""),
            ]

            with self.assertRaisesRegex(TimeoutError, "命令执行超时"):
                tool.run({"content": "pnpm dev", "timeout": 2}, self.context)

        self.assertEqual(mock_run.call_args.args[0], ["taskkill", "/PID", "4321", "/T", "/F"])

    def test_excecute_tool_uses_same_timeout_contract(self) -> None:
        tool = ExcecuteTool()

        with self.assertRaisesRegex(ValueError, "timeout 为必填参数"):
            tool.run({"content": "Get-Date"}, self.context)

    def test_execute_can_continue_with_terminal_input(self) -> None:
        self.interactive_session = InteractiveCommandSession(workspace=self.workspace)
        interactive_context = ToolContext(
            workspace=self.workspace,
            metadata={"interactive_command_session": self.interactive_session},
        )
        execute_tool = ExecuteTool()
        terminal_input_tool = TerminalInputTool()

        first_result = execute_tool.run(
            {
                "content": "[Console]::Write('Name: '); $name = [Console]::ReadLine(); Write-Output ('Hello ' + $name)",
                "timeout": 3,
            },
            interactive_context,
        )

        self.assertEqual(first_result["status"], "running")
        self.assertIn("Name:", str(first_result["full_output"]))

        second_result = terminal_input_tool.run(
            {
                "content": "Alice",
                "timeout": 3,
            },
            interactive_context,
        )

        self.assertEqual(second_result["status"], "completed")
        self.assertIn("Hello Alice", str(second_result["full_output"]))

    def test_terminal_input_requires_active_command(self) -> None:
        self.interactive_session = InteractiveCommandSession(workspace=self.workspace)
        interactive_context = ToolContext(
            workspace=self.workspace,
            metadata={"interactive_command_session": self.interactive_session},
        )
        terminal_input_tool = TerminalInputTool()

        with self.assertRaisesRegex(RuntimeError, "当前没有可继续输入的终端命令"):
            terminal_input_tool.run({"content": "y", "timeout": 1}, interactive_context)

    def test_terminal_wait_can_observe_background_progress(self) -> None:
        self.interactive_session = InteractiveCommandSession(workspace=self.workspace)
        interactive_context = ToolContext(
            workspace=self.workspace,
            metadata={"interactive_command_session": self.interactive_session},
        )
        execute_tool = ExecuteTool()
        wait_tool = TerminalWaitTool()

        first_result = execute_tool.run(
            {
                "content": "Write-Output 'Installing'; Start-Sleep -Seconds 2; Write-Output 'Done'",
                "timeout": 1,
            },
            interactive_context,
        )

        self.assertEqual(first_result["status"], "running")
        self.assertFalse(bool(first_result["awaiting_input"]))
        self.assertIn("Installing", str(first_result["full_output"]))

        second_result = wait_tool.run({"timeout": 4}, interactive_context)

        self.assertEqual(second_result["status"], "completed")
        self.assertIn("Done", str(second_result["full_output"]))

    def test_prompt_detection_uses_last_visible_line(self) -> None:
        self.interactive_session = InteractiveCommandSession(workspace=self.workspace)

        self.assertTrue(self.interactive_session._looks_like_prompt("Question?\n"))
        self.assertFalse(self.interactive_session._looks_like_prompt("Question?\nInstalling dependencies...\n"))


if __name__ == "__main__":
    unittest.main()
