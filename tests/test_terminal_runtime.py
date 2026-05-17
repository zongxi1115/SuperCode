import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

from fastapi_app import main as api_main


class _FakePtyProcess:
    last_command: str | None = None

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.controls: list[str] = []
        self.alive = True

    @classmethod
    def spawn(cls, command: str) -> "_FakePtyProcess":
        cls.last_command = command
        return cls()

    def write(self, payload: str) -> None:
        self.writes.append(payload)

    def read(self, size: int) -> str:
        raise EOFError

    def isalive(self) -> bool:
        return self.alive

    def sendcontrol(self, key: str) -> None:
        self.controls.append(key)

    def terminate(self, force: bool = True) -> None:
        self.alive = False


class _FakeTerminalRuntime:
    def __init__(self, supports_interrupt: bool = True) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.supports_interrupt = supports_interrupt

    def send_input(self, command: str, submit: bool = True) -> None:
        self.calls.append((command, submit))

    def interrupt(self) -> bool:
        return self.supports_interrupt

    def snapshot(self, session_id: str) -> api_main.TerminalSnapshotResponse:
        return api_main.TerminalSnapshotResponse(
            sessionId=session_id,
            output="terminal output",
            revision=2,
            isAlive=True,
            shell="powershell",
            backend="winpty",
            cwd="D:\\vibe_projs\\SuperCode\\frontend",
            supportsInterrupt=self.supports_interrupt,
            supportsRawInput=True,
        )


class TerminalRuntimeTests(unittest.TestCase):
    def test_terminal_runtime_prefers_winpty_and_supports_interrupt(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-terminal-runtime-")).resolve()

        with mock.patch.object(api_main, "PtyProcess", _FakePtyProcess):
            runtime = api_main.TerminalRuntime(workspace=str(workspace))
            try:
                runtime.send_input("", submit=True)
                runtime.send_input("Get-Location", submit=True)

                self.assertEqual(runtime.backend, "winpty")
                self.assertTrue(runtime.supports_interrupt)
                self.assertTrue(runtime.interrupt())
                self.assertIsNotNone(runtime.pty_process)
                self.assertEqual(runtime.pty_process.writes[:2], ["\n", "Get-Location\n"])
                self.assertEqual(runtime.pty_process.controls, ["c"])
                self.assertIn("Set-Location -LiteralPath", _FakePtyProcess.last_command or "")
                self.assertIn("$env:PYTHONIOENCODING = 'utf-8';", _FakePtyProcess.last_command or "")
                self.assertIn("$env:PYTHONUTF8 = '1';", _FakePtyProcess.last_command or "")
            finally:
                runtime.close()

    def test_terminal_input_endpoint_allows_blank_submit_for_interactive_enter(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-terminal-endpoint-")).resolve()
        runtime = _FakeTerminalRuntime()
        session = api_main.UISession(
            session_id="session-terminal-input",
            model="test-model",
            workspace=str(workspace),
            terminal_runtime=runtime,
        )

        with mock.patch.object(api_main, "require_session", return_value=session):
            response = asyncio.run(
                api_main.post_session_terminal_input(
                    "session-terminal-input",
                    api_main.TerminalInputRequest(command="", submit=True),
                )
            )

        payload = json.loads(response.body)
        self.assertEqual(runtime.calls, [("", True)])
        self.assertEqual(payload["cwd"], "D:\\vibe_projs\\SuperCode\\frontend")
        self.assertTrue(payload["supportsInterrupt"])

    def test_terminal_input_endpoint_rejects_empty_payload_without_submit(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-terminal-empty-")).resolve()
        runtime = _FakeTerminalRuntime()
        session = api_main.UISession(
            session_id="session-terminal-empty",
            model="test-model",
            workspace=str(workspace),
            terminal_runtime=runtime,
        )

        with mock.patch.object(api_main, "require_session", return_value=session):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(
                    api_main.post_session_terminal_input(
                        "session-terminal-empty",
                        api_main.TerminalInputRequest(command="", submit=False),
                    )
                )

        self.assertEqual(error.exception.status_code, 400)

    def test_terminal_control_endpoint_rejects_interrupt_when_backend_cannot_handle_it(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-terminal-control-")).resolve()
        runtime = _FakeTerminalRuntime(supports_interrupt=False)
        session = api_main.UISession(
            session_id="session-terminal-control",
            model="test-model",
            workspace=str(workspace),
            terminal_runtime=runtime,
        )

        with mock.patch.object(api_main, "require_session", return_value=session):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(
                    api_main.post_session_terminal_control(
                        "session-terminal-control",
                        api_main.TerminalControlRequest(action="interrupt"),
                    )
                )

        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
