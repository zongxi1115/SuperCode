from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi_app.api_models import TerminalSnapshotResponse


@dataclass
class TerminalRuntimeBase:
    workspace: str
    shell: str = "powershell"
    output: str = ""
    revision: int = 0
    backend: str = field(default="subprocess", init=False)
    current_directory: str = field(default="", init=False)
    supports_interrupt: bool = field(default=False, init=False)
    supports_raw_input: bool = field(default=True, init=False)
    pty_process: Any | None = field(default=None, init=False, repr=False)
    process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    stdout_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    stderr_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    prompt_pattern: re.Pattern[str] = field(
        default=re.compile(r"(?m)^PS (?P<path>[^\r\n>]+)>"),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.current_directory = self.workspace
        pty_process_class = self._get_pty_process_class()
        if pty_process_class is not None:
            try:
                self._start_winpty(pty_process_class)
                return
            except Exception:
                self.pty_process = None
        self.process = subprocess.Popen(
            [
                "powershell",
                "-NoLogo",
                "-NoProfile",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "chcp 65001 > $null"
                ),
            ],
            cwd=self.workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.backend = "subprocess"
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_pipe_stream,
            args=(self.process.stdout,),
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._pump_pipe_stream,
            args=(self.process.stderr,),
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _get_pty_process_class(self) -> Any | None:
        return None

    def _start_winpty(self, pty_process_class: Any) -> None:
        command = self._build_powershell_command()
        self.pty_process = pty_process_class.spawn(command)
        self.backend = "winpty"
        self.supports_interrupt = True
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_pty_stream,
            daemon=True,
        )
        self.stdout_thread.start()

    def _build_powershell_command(self) -> str:
        escaped_workspace = self.workspace.replace("'", "''")
        bootstrap = (
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "chcp 65001 > $null; "
            f"Set-Location -LiteralPath '{escaped_workspace}'"
        )
        return (
            "powershell "
            "-NoLogo "
            "-NoProfile "
            "-NoExit "
            "-ExecutionPolicy Bypass "
            f'-Command "{bootstrap}"'
        )

    def _pump_pty_stream(self) -> None:
        if self.pty_process is None:
            return
        try:
            while self.pty_process.isalive():
                chunk = self.pty_process.read(1024)
                if chunk == "":
                    break
                self.append_output(chunk)
        except EOFError:
            return
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def _pump_pipe_stream(self, stream: Any) -> None:
        try:
            while True:
                chunk = stream.readline()
                if chunk == "":
                    break
                self.append_output(chunk)
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def append_output(self, text: str) -> None:
        with self.lock:
            self.output += text
            inferred_cwd = self._infer_current_directory(self.output[-4096:])
            if inferred_cwd:
                self.current_directory = inferred_cwd
            self.revision += 1

    def _infer_current_directory(self, text: str) -> str | None:
        matches = list(self.prompt_pattern.finditer(text))
        if not matches:
            return None
        return matches[-1].group("path").strip()

    def send_input(self, content: str, submit: bool = True) -> None:
        payload = content
        if submit:
            payload += "\n"
        if payload == "":
            return
        if self.pty_process is not None:
            self.pty_process.write(payload)
            return
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("terminal process is not available")
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def write(self, command: str) -> None:
        self.send_input(command, submit=True)

    def interrupt(self) -> bool:
        if self.pty_process is None or not hasattr(self.pty_process, "sendcontrol"):
            return False
        self.pty_process.sendcontrol("c")
        return True

    def snapshot(self, session_id: str) -> TerminalSnapshotResponse:
        with self.lock:
            return TerminalSnapshotResponse(
                sessionId=session_id,
                output=self.output,
                revision=self.revision,
                isAlive=self.is_alive(),
                shell=self.shell,
                backend=self.backend,
                cwd=self.current_directory or self.workspace,
                supportsInterrupt=self.supports_interrupt,
                supportsRawInput=self.supports_raw_input,
            )

    def is_alive(self) -> bool:
        if self.pty_process is not None:
            return bool(self.pty_process.isalive())
        return self.process is not None and self.process.poll() is None

    def clear(self) -> None:
        with self.lock:
            self.output = ""
            self.revision += 1

    def close(self) -> None:
        if self.pty_process is not None:
            try:
                self.pty_process.write("exit\n")
            except Exception:
                pass
            try:
                self.pty_process.terminate(force=True)
            except Exception:
                pass
            self.pty_process = None
            return
        if self.process is None:
            return
        try:
            if self.process.stdin is not None:
                self.process.stdin.write("exit\n")
                self.process.stdin.flush()
        except Exception:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
