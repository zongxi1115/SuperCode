from __future__ import annotations

import base64
import codecs
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from agent.rolling_text_buffer import RollingTextBuffer
from fastapi_app.api_models import TerminalSnapshotResponse

MAX_TERMINAL_OUTPUT_CHARS = 300_000
TERMINAL_CWD_TAIL_CHARS = 4096
PIPE_READ_CHUNK_SIZE = 4096


TERMINAL_INTERRUPT_KEYS = {
    "ctrl+c",
    "ctrl-c",
    "ctrl_c",
    "control+c",
    "control-c",
    "interrupt",
    "cancel",
    "^c",
    "\x03",
}

TERMINAL_KEY_INPUTS = {
    "enter": "\n",
    "return": "\n",
    "newline": "\n",
    "linefeed": "\n",
    "tab": "\t",
    "escape": "\x1b",
    "esc": "\x1b",
    "backspace": "\b",
    "delete": "\x7f",
    "ctrl+d": "\x04",
    "ctrl-d": "\x04",
    "ctrl_d": "\x04",
    "eof": "\x04",
    "ctrl+z": "\x1a",
    "ctrl-z": "\x1a",
    "ctrl_z": "\x1a",
    "up": "\x1b[A",
    "arrowup": "\x1b[A",
    "down": "\x1b[B",
    "arrowdown": "\x1b[B",
    "right": "\x1b[C",
    "arrowright": "\x1b[C",
    "left": "\x1b[D",
    "arrowleft": "\x1b[D",
}


def _normalize_terminal_key(value: object) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    return re.sub(r"\s*([+_-])\s*", r"\1", normalized)


@dataclass
class TerminalRuntimeBase:
    workspace: str
    shell: str = "powershell"
    revision: int = 0
    backend: str = field(default="subprocess", init=False)
    current_directory: str = field(default="", init=False)
    supports_interrupt: bool = field(default=False, init=False)
    supports_raw_input: bool = field(default=True, init=False)
    supports_resize: bool = field(default=False, init=False)
    pty_process: Any | None = field(default=None, init=False, repr=False)
    process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    output_subscribers: list[Callable[[str], None]] = field(
        default_factory=list,
        init=False,
        repr=False,
    )
    output_buffer: RollingTextBuffer = field(
        default_factory=lambda: RollingTextBuffer(MAX_TERMINAL_OUTPUT_CHARS),
        init=False,
        repr=False,
    )
    recent_output_tail: str = field(default="", init=False, repr=False)
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
                    "$env:PYTHONIOENCODING = 'utf-8'; "
                    "$env:PYTHONUTF8 = '1'; "
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
        self.supports_resize = True
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_pty_stream,
            daemon=True,
        )
        self.stdout_thread.start()

    def _build_powershell_command(self) -> str:
        encoded_bootstrap = base64.b64encode(
            self._build_powershell_bootstrap().encode("utf-16le")
        ).decode("ascii")
        return (
            "powershell "
            "-NoLogo "
            "-NoProfile "
            "-NoExit "
            "-ExecutionPolicy Bypass "
            f"-EncodedCommand {encoded_bootstrap}"
        )

    def _build_powershell_bootstrap(self) -> str:
        escaped_workspace = self.workspace.replace("'", "''")
        return (
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$env:PYTHONIOENCODING = 'utf-8'; "
            "$env:PYTHONUTF8 = '1'; "
            "chcp 65001 > $null; "
            f"Set-Location -LiteralPath '{escaped_workspace}'"
        )

    def _pump_pty_stream(self) -> None:
        if self.pty_process is None:
            return
        try:
            while self.pty_process.isalive():
                chunk = self.pty_process.read(8192)
                if chunk == "":
                    break
                self.append_output(chunk)
        except EOFError:
            return
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def _pump_pipe_stream(self, stream: Any) -> None:
        if stream is None:
            return
        try:
            buffered_stream = getattr(stream, "buffer", None)
            if buffered_stream is not None and hasattr(buffered_stream, "read1"):
                decoder = codecs.getincrementaldecoder(
                    getattr(stream, "encoding", "utf-8")
                )(getattr(stream, "errors", "replace"))
                while True:
                    chunk = buffered_stream.read1(PIPE_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    if text:
                        self.append_output(text)
                tail = decoder.decode(b"", final=True)
                if tail:
                    self.append_output(tail)
                return

            while True:
                chunk = stream.read(PIPE_READ_CHUNK_SIZE)
                if chunk == "":
                    break
                self.append_output(chunk)
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def append_output(self, text: str) -> None:
        if text == "":
            return
        with self.lock:
            self.output_buffer.append(text)
            self.recent_output_tail = (
                f"{self.recent_output_tail}{text}"
            )[-TERMINAL_CWD_TAIL_CHARS:]
            inferred_cwd = self._infer_current_directory(self.recent_output_tail)
            if inferred_cwd:
                self.current_directory = inferred_cwd
            self.revision += 1
            subscribers = list(self.output_subscribers)

        for subscriber in subscribers:
            try:
                subscriber(text)
            except Exception:
                continue

    def _infer_current_directory(self, text: str) -> str | None:
        matches = list(self.prompt_pattern.finditer(text))
        if not matches:
            return None
        return matches[-1].group("path").strip()

    def send_input(self, content: str, submit: bool = True) -> None:
        payload = content
        if submit:
            payload += "\n"
        self.write_raw(payload)

    def write_raw(self, payload: str) -> None:
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
        self.write_raw(command)

    def read_loop(self, on_data: Callable[[str], None]) -> Callable[[], None]:
        return self.subscribe_output(on_data)

    def subscribe_output(self, on_data: Callable[[str], None]) -> Callable[[], None]:
        with self.lock:
            self.output_subscribers.append(on_data)

        def unsubscribe() -> None:
            with self.lock:
                self.output_subscribers = [
                    subscriber
                    for subscriber in self.output_subscribers
                    if subscriber is not on_data
                ]

        return unsubscribe

    def send_key(self, key: str) -> bool:
        normalized_key = _normalize_terminal_key(key)
        if normalized_key in TERMINAL_INTERRUPT_KEYS:
            return self.interrupt()
        payload = TERMINAL_KEY_INPUTS.get(normalized_key)
        if payload is None:
            raise ValueError(f"不支持的终端按键: {key}")
        self.send_input(payload, submit=False)
        return True

    def interrupt(self) -> bool:
        if self.pty_process is None or not hasattr(self.pty_process, "sendcontrol"):
            return False
        self.pty_process.sendcontrol("c")
        return True

    def resize(self, cols: int, rows: int) -> bool:
        if self.pty_process is None:
            return False

        normalized_cols = max(int(cols or 0), 2)
        normalized_rows = max(int(rows or 0), 1)
        method_attempts = (
            ("setwinsize", (normalized_rows, normalized_cols)),
            ("set_size", (normalized_cols, normalized_rows)),
            ("resize", (normalized_cols, normalized_rows)),
        )
        for method_name, args in method_attempts:
            method = getattr(self.pty_process, method_name, None)
            if callable(method):
                try:
                    method(*args)
                    return True
                except Exception:
                    continue

        low_level_pty = getattr(self.pty_process, "pty", None)
        method = getattr(low_level_pty, "set_size", None)
        if callable(method):
            try:
                method(normalized_cols, normalized_rows)
                return True
            except Exception:
                return False
        return False

    def snapshot(
        self,
        session_id: str,
        *,
        include_output: bool = True,
        output_tail_chars: int | None = None,
    ) -> TerminalSnapshotResponse:
        with self.lock:
            if not include_output:
                output = ""
            elif output_tail_chars is not None:
                output = self.output_buffer.tail(output_tail_chars)
            else:
                output = self.output_buffer.get_text()
            return TerminalSnapshotResponse(
                sessionId=session_id,
                output=output,
                revision=self.revision,
                isAlive=self.is_alive(),
                shell=self.shell,
                backend=self.backend,
                cwd=self.current_directory or self.workspace,
                supportsInterrupt=self.supports_interrupt,
                supportsRawInput=self.supports_raw_input,
                supportsResize=self.supports_resize,
            )

    def is_alive(self) -> bool:
        if self.pty_process is not None:
            return bool(self.pty_process.isalive())
        return self.process is not None and self.process.poll() is None

    def clear(self) -> None:
        with self.lock:
            self.output_buffer.clear()
            self.recent_output_tail = ""
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
