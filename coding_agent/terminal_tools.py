from __future__ import annotations

import codecs
import json
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.rolling_text_buffer import RollingTextBuffer
from zonix.tools import ToolContext

from .tool_common import (
    INTERACTIVE_COMMAND_MAX_OUTPUT_CHARS,
    INTERACTIVE_INPUT_PROMPT_IDLE_SECONDS,
    INTERACTIVE_POLL_SECONDS,
    INTERACTIVE_PROMPT_TAIL_CHARS,
    INTERACTIVE_STREAM_READ_CHUNK_SIZE,
    _build_powershell_utf8_command,
    _hidden_windows_process_kwargs,
    _kill_process_tree,
    _kill_processes_by_pid,
    _parse_bool_argument,
)

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

TERMINAL_INLINE_KEY_TOKENS = {
    "<enter>": "\n",
    "[enter]": "\n",
    "{enter}": "\n",
    "<tab>": "\t",
    "[tab]": "\t",
    "{tab}": "\t",
    "<esc>": "\x1b",
    "<escape>": "\x1b",
    "[esc]": "\x1b",
    "[escape]": "\x1b",
    "<backspace>": "\b",
    "[backspace]": "\b",
    "<delete>": "\x7f",
    "[delete]": "\x7f",
    "<ctrl+d>": "\x04",
    "[ctrl+d]": "\x04",
    "<ctrl+z>": "\x1a",
    "[ctrl+z]": "\x1a",
}


def _normalize_terminal_key(value: object) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    return re.sub(r"\s*([+_-])\s*", r"\1", normalized)


def _expand_terminal_inline_key_tokens(content: str) -> str:
    expanded = content
    for token, replacement in TERMINAL_INLINE_KEY_TOKENS.items():
        expanded = expanded.replace(token, replacement)
    return expanded


def _query_process_table() -> list[dict[str, Any]]:
    """读取系统进程快照，用于定位由 AI 拉起但已脱离父 shell 的残留进程。"""

    if sys.platform == "win32":
        command = (
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId, ParentProcessId, Name, CommandLine | "
            "ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                _build_powershell_utf8_command(command),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                **_hidden_windows_process_kwargs(),
            )
        except Exception:
            return []

        raw = completed.stdout.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []

        rows = parsed if isinstance(parsed, list) else [parsed]
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                pid = int(row.get("ProcessId") or 0)
                parent_pid = int(row.get("ParentProcessId") or 0)
            except (TypeError, ValueError):
                continue
            normalized.append(
                {
                    "pid": pid,
                    "parent_pid": parent_pid,
                    "name": str(row.get("Name") or ""),
                    "command_line": str(row.get("CommandLine") or ""),
                }
            )
        return normalized

    return []


def _collect_process_tree(
    root_pid: int, process_table: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """基于 ParentProcessId 递归找出 root_pid 及其后代。"""

    if root_pid <= 0:
        return []

    by_pid: dict[int, dict[str, Any]] = {}
    by_parent_pid: dict[int, list[int]] = {}
    for row in process_table:
        try:
            pid = int(row.get("pid") or 0)
            parent_pid = int(row.get("parent_pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        by_pid[pid] = row
        by_parent_pid.setdefault(parent_pid, []).append(pid)

    visited: set[int] = set()
    queue: deque[int] = deque([root_pid])
    collected: list[dict[str, Any]] = []

    while queue:
        current_pid = queue.popleft()
        if current_pid in visited:
            continue
        visited.add(current_pid)

        current = by_pid.get(current_pid)
        if current is not None:
            collected.append(
                {
                    "pid": current_pid,
                    "parent_pid": int(current.get("parent_pid") or 0),
                    "name": str(current.get("name") or ""),
                    "command_line": str(current.get("command_line") or ""),
                    "is_root": current_pid == root_pid,
                }
            )

        for child_pid in by_parent_pid.get(current_pid, []):
            if child_pid not in visited:
                queue.append(child_pid)

    collected.sort(
        key=lambda item: (
            0 if bool(item.get("is_root")) else 1,
            int(item.get("pid") or 0),
        )
    )
    return collected


@dataclass
class ManagedCommandProcess:
    """记录 AI 工具拉起过的命令根进程，便于后续监控和终止。"""

    terminal_id: str
    command: str
    root_pid: int
    started_at: float = field(default_factory=time.time)
    terminated_at: float | None = None
    last_return_code: int | None = None
    output: str = ""


@dataclass
class InteractiveCommand:
    """保存一条可继续输入的命令进程。"""

    terminal_id: str
    command: str
    process: subprocess.Popen[str]
    output_buffer: RollingTextBuffer = field(
        default_factory=lambda: RollingTextBuffer(INTERACTIVE_COMMAND_MAX_OUTPUT_CHARS)
    )
    reported_offset: int = 0
    last_output_at: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    stdout_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    stderr_thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.stdout_thread = threading.Thread(
            target=self._pump_stream,
            args=(self.process.stdout,),
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._pump_stream,
            args=(self.process.stderr,),
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _pump_stream(self, stream: Any) -> None:
        if stream is None:
            return
        try:
            buffered_stream = getattr(stream, "buffer", None)
            if buffered_stream is not None and hasattr(buffered_stream, "read1"):
                decoder = codecs.getincrementaldecoder(
                    getattr(stream, "encoding", "utf-8")
                )(getattr(stream, "errors", "replace"))
                while True:
                    chunk = buffered_stream.read1(INTERACTIVE_STREAM_READ_CHUNK_SIZE)
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
                chunk = stream.read(INTERACTIVE_STREAM_READ_CHUNK_SIZE)
                if chunk == "":
                    break
                self.append_output(chunk)
        except Exception:
            self.append_output("\n[interactive command reader stopped unexpectedly]\n")

    def append_output(self, text: str) -> None:
        with self.lock:
            self.output_buffer.append(text)
            self.last_output_at = time.monotonic()

    def mark_activity(self) -> None:
        with self.lock:
            self.last_output_at = time.monotonic()

    def snapshot_output(self) -> str:
        with self.lock:
            return self.output_buffer.get_text()

    def snapshot_output_state(
        self,
        *,
        tail_chars: int | None = None,
        after_offset: int | None = None,
    ) -> tuple[str, int, int]:
        with self.lock:
            start_offset = self.output_buffer.start_offset
            end_offset = self.output_buffer.end_offset
            full_output = self.output_buffer.get_text()

            if after_offset is not None:
                if after_offset > end_offset:
                    return "", end_offset, end_offset
                if start_offset <= after_offset <= end_offset:
                    start_index = after_offset - start_offset
                    return full_output[start_index:], after_offset, end_offset

            if tail_chars is not None and tail_chars > 0:
                output = self.output_buffer.tail(tail_chars)
                return output, end_offset - len(output), end_offset

            return full_output, start_offset, end_offset

    def snapshot_progress(self) -> tuple[str, int, int]:
        with self.lock:
            return (
                self.output_buffer.get_text(),
                self.reported_offset,
                self.output_buffer.end_offset,
            )

    def consume_delta(self) -> tuple[str, str]:
        with self.lock:
            full_output = self.output_buffer.get_text()
            start_offset = self.output_buffer.start_offset
            effective_reported_offset = max(self.reported_offset, start_offset)
            delta = full_output[effective_reported_offset - start_offset :]
            self.reported_offset = self.output_buffer.end_offset
        return delta, full_output

    def idle_for(self) -> float:
        with self.lock:
            return time.monotonic() - self.last_output_at

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def write_input(self, content: str, *, submit: bool = True) -> None:
        if self.process.stdin is None or not self.is_alive():
            raise RuntimeError("当前命令已经不能继续输入。")
        payload = content
        if submit and not payload.endswith(("\n", "\r")):
            payload = f"{payload}\n"
        if payload == "":
            return
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        with self.lock:
            self.last_output_at = time.monotonic()

    def close(self) -> None:
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except Exception:
            pass
        _kill_process_tree(self.process)
        try:
            self.process.wait(timeout=2)
        except Exception:
            pass
        self.wait_for_readers()
        self.close_streams()

    def wait_for_readers(self) -> None:
        for thread in (self.stdout_thread, self.stderr_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=0.2)

    def close_streams(self) -> None:
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass


@dataclass
class CompletedCommandResult:
    """缓存已完成终端的最终结果，避免活动句柄释放后无法回读。"""

    result: dict[str, object]
    delivered: bool = False


@dataclass
class InteractiveCommandSession:
    """管理当前会话里多个可继续输入的命令。"""

    workspace: Path
    input_prompt_idle_timeout: float = INTERACTIVE_INPUT_PROMPT_IDLE_SECONDS
    active_commands: dict[str, InteractiveCommand] = field(
        default_factory=dict, init=False, repr=False
    )
    completed_commands: dict[str, CompletedCommandResult] = field(
        default_factory=dict, init=False, repr=False
    )
    managed_processes: dict[str, ManagedCommandProcess] = field(
        default_factory=dict, init=False, repr=False
    )
    next_terminal_index: int = field(default=1, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start_command(
        self,
        command: str,
        timeout: int,
        terminal_id: str | None = None,
    ) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            resolved_terminal_id = terminal_id or self._allocate_terminal_id_locked()
            existing_command = self.active_commands.get(resolved_terminal_id)
            if existing_command is not None and existing_command.is_alive():
                raise RuntimeError(
                    f"终端 {resolved_terminal_id} 已在运行，请改用新的 terminal_id，"
                    "或使用 task_input / task_wait 继续交互。"
                )
            self.completed_commands.pop(resolved_terminal_id, None)

            process = self._spawn_process(command)
            active_command = InteractiveCommand(
                terminal_id=resolved_terminal_id,
                command=command,
                process=process,
            )
            self.active_commands[resolved_terminal_id] = active_command
            self.managed_processes[resolved_terminal_id] = ManagedCommandProcess(
                terminal_id=resolved_terminal_id,
                command=command,
                root_pid=process.pid,
            )

        return self._await_progress(active_command, timeout)

    def send_input(
        self,
        content: str,
        timeout: int,
        terminal_id: str | None = None,
        *,
        submit: bool = True,
    ) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            if terminal_id:
                completed_result = self._get_completed_result_locked(terminal_id)
                if completed_result is not None:
                    raise RuntimeError(f"终端 {terminal_id} 已完成，无法继续输入。")
            active_command = self._resolve_active_command_locked(terminal_id)

        active_command.write_input(content, submit=submit)
        return self._await_progress(active_command, timeout)

    def interrupt_command(
        self,
        terminal_id: str | None = None,
    ) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            active_command = self._resolve_active_command_locked(terminal_id)
            self.active_commands.pop(active_command.terminal_id, None)

        active_command.close()

        with self.lock:
            managed_process = self.managed_processes.get(active_command.terminal_id)
            if managed_process is not None:
                managed_process.terminated_at = time.time()
                managed_process.last_return_code = active_command.process.returncode
            result = self._build_result(
                active_command,
                status="terminated",
                exit_reason="interrupted",
            )
            if managed_process is not None:
                managed_process.output = str(result.get("full_output") or "")
            self.completed_commands[active_command.terminal_id] = (
                CompletedCommandResult(
                    result=dict(result),
                    delivered=True,
                )
            )
        active_command.close_streams()
        return result

    def wait_for_command(
        self,
        timeout: int,
        terminal_id: str | None = None,
    ) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            completed_result = self._resolve_completed_result_for_wait_locked(
                terminal_id
            )
            if completed_result is not None:
                return completed_result
            active_command = self._resolve_active_command_locked(terminal_id)

        return self._await_progress(
            active_command,
            timeout,
            return_on_existing_prompt=True,
        )

    def close(self) -> None:
        with self.lock:
            active_commands = list(self.active_commands.values())
            self.active_commands = {}
            self.completed_commands = {}

        for active_command in active_commands:
            managed_process = self.managed_processes.get(active_command.terminal_id)
            active_command.close()
            if managed_process is not None:
                managed_process.terminated_at = time.time()
                managed_process.last_return_code = active_command.process.returncode
                managed_process.output = active_command.snapshot_output()

    def list_managed_processes(self, only_active: bool = False) -> list[dict[str, Any]]:
        with self.lock:
            self._clear_finished_locked()
            managed_processes = list(self.managed_processes.values())
            active_commands = dict(self.active_commands)

        process_table = _query_process_table()
        rows = [
            self._serialize_managed_process(
                managed_process,
                active_commands.get(managed_process.terminal_id),
                process_table,
            )
            for managed_process in managed_processes
        ]
        if only_active:
            rows = [
                row for row in rows if str(row.get("status")) in {"running", "orphaned"}
            ]
        rows.sort(key=lambda row: int(row.get("startedAt") or 0), reverse=True)
        return rows

    def get_managed_process_output(
        self,
        terminal_id: str,
        *,
        tail_chars: int | None = None,
        after_offset: int | None = None,
    ) -> dict[str, Any]:
        normalized_terminal_id = terminal_id.strip()
        with self.lock:
            self._clear_finished_locked()
            managed_process = self.managed_processes.get(normalized_terminal_id)
            active_command = self.active_commands.get(normalized_terminal_id)
            completed_result = self.completed_commands.get(normalized_terminal_id)

        if managed_process is None:
            raise RuntimeError(f"未找到受管进程: {terminal_id}")

        process_table = _query_process_table()
        process_payload = self._serialize_managed_process(
            managed_process,
            active_command,
            process_table,
        )
        output, start_offset, end_offset = self._snapshot_managed_process_output(
            managed_process,
            active_command,
            completed_result,
            tail_chars=tail_chars,
            after_offset=after_offset,
        )
        return {
            "terminalId": managed_process.terminal_id,
            "output": output,
            "startOffset": start_offset,
            "endOffset": end_offset,
            "truncated": start_offset > 0,
            "process": process_payload,
        }

    def terminate_command(self, terminal_id: str) -> dict[str, Any]:
        with self.lock:
            active_command = self.active_commands.pop(terminal_id, None)
            managed_process = self.managed_processes.get(terminal_id)

        if managed_process is None:
            raise RuntimeError(f"未找到受管进程: {terminal_id}")

        if active_command is not None:
            active_command.close()
            managed_process.last_return_code = active_command.process.returncode
            managed_process.output = active_command.snapshot_output()

        process_table = _query_process_table()
        descendants = _collect_process_tree(managed_process.root_pid, process_table)
        _kill_processes_by_pid(
            [
                managed_process.root_pid,
                *[int(item.get("pid") or 0) for item in descendants],
            ]
        )
        managed_process.terminated_at = time.time()

        refreshed_table = _query_process_table()
        return self._serialize_managed_process(managed_process, None, refreshed_table)

    def terminate_all(self) -> list[dict[str, Any]]:
        active_processes = self.list_managed_processes(only_active=True)
        terminated: list[dict[str, Any]] = []
        for process in active_processes:
            terminal_id = str(process.get("terminalId") or "").strip()
            if not terminal_id:
                continue
            try:
                terminated.append(self.terminate_command(terminal_id))
            except Exception:
                continue
        return terminated

    def _spawn_process(self, command: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            _build_powershell_utf8_command(command),
            cwd=self.workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_hidden_windows_process_kwargs(new_process_group=True),
        )

    def _await_progress(
        self,
        active_command: InteractiveCommand,
        timeout: int,
        return_on_existing_prompt: bool = False,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        _, start_reported_offset, _ = active_command.snapshot_progress()

        while True:
            if not active_command.is_alive():
                active_command.wait_for_readers()
                with self.lock:
                    current = self.active_commands.get(active_command.terminal_id)
                    if current is active_command:
                        self.active_commands.pop(active_command.terminal_id, None)
                        result = self._cache_completed_result_locked(
                            active_command,
                            delivered=True,
                        )
                    else:
                        result = self._get_completed_result_locked(
                            active_command.terminal_id,
                            mark_delivered=False,
                        ) or self._build_result(active_command, status="completed")
                active_command.close_streams()
                return result

            full_output, _, current_end_offset = active_command.snapshot_progress()
            saw_new_output = current_end_offset > start_reported_offset
            prompt_text = self._extract_prompt_text(full_output)
            if prompt_text is not None and (
                saw_new_output or return_on_existing_prompt
            ):
                if self._prompt_needs_idle_confirmation(full_output) and (
                    active_command.idle_for() < self.input_prompt_idle_timeout
                ):
                    pass
                else:
                    return self._build_result(
                        active_command,
                        status="running",
                        exit_reason="awaiting_input",
                        input_prompt=prompt_text,
                    )

            if time.monotonic() >= deadline:
                return self._build_result(
                    active_command,
                    status="running",
                    exit_reason="timeout",
                )

            time.sleep(INTERACTIVE_POLL_SECONDS)

    def _build_result(
        self,
        active_command: InteractiveCommand,
        status: str,
        *,
        exit_reason: str | None = None,
        input_prompt: str | None = None,
    ) -> dict[str, object]:
        delta, full_output = active_command.consume_delta()
        managed_process = self.managed_processes.get(active_command.terminal_id)
        if managed_process is not None:
            managed_process.last_return_code = active_command.process.returncode
        resolved_input_prompt = input_prompt
        if resolved_input_prompt is None and status == "running":
            resolved_input_prompt = self._extract_prompt_text(full_output)
        awaiting_input = status == "running" and resolved_input_prompt is not None
        resolved_exit_reason = exit_reason or (
            "completed" if status == "completed" else "running"
        )
        return {
            "terminal_id": active_command.terminal_id,
            "task_id": active_command.terminal_id,
            "status": status,
            "exit_reason": resolved_exit_reason,
            "command": active_command.command,
            "delta": delta,
            "full_output": full_output,
            "return_code": active_command.process.returncode,
            "awaiting_input": awaiting_input,
            "needs_input": awaiting_input,
            "input_prompt": resolved_input_prompt,
            "input_request": self._build_input_request(
                active_command, resolved_input_prompt
            ),
        }

    def _clear_finished_locked(self) -> None:
        finished_ids = [
            terminal_id
            for terminal_id, active_command in self.active_commands.items()
            if not active_command.is_alive()
        ]
        for terminal_id in finished_ids:
            finished_command = self.active_commands.pop(terminal_id, None)
            managed_process = self.managed_processes.get(terminal_id)
            if finished_command is not None and managed_process is not None:
                finished_command.wait_for_readers()
                managed_process.last_return_code = finished_command.process.returncode
                self._cache_completed_result_locked(finished_command, delivered=False)
                finished_command.close_streams()

    def _allocate_terminal_id_locked(self) -> str:
        while True:
            terminal_id = f"terminal-{self.next_terminal_index}"
            self.next_terminal_index += 1
            if terminal_id not in self.active_commands:
                return terminal_id

    def _cache_completed_result_locked(
        self,
        active_command: InteractiveCommand,
        *,
        delivered: bool,
    ) -> dict[str, object]:
        result = self._build_result(active_command, status="completed")
        self.completed_commands[active_command.terminal_id] = CompletedCommandResult(
            result=dict(result),
            delivered=delivered,
        )
        managed_process = self.managed_processes.get(active_command.terminal_id)
        if managed_process is not None:
            managed_process.output = str(result.get("full_output") or "")
        return dict(result)

    def _snapshot_managed_process_output(
        self,
        managed_process: ManagedCommandProcess,
        active_command: InteractiveCommand | None,
        completed_result: CompletedCommandResult | None,
        *,
        tail_chars: int | None,
        after_offset: int | None,
    ) -> tuple[str, int, int]:
        if active_command is not None and active_command.is_alive():
            return active_command.snapshot_output_state(
                tail_chars=tail_chars,
                after_offset=after_offset,
            )

        output = managed_process.output
        if completed_result is not None:
            full_output = completed_result.result.get("full_output")
            if isinstance(full_output, str):
                output = full_output

        end_offset = len(output)
        if after_offset is not None:
            if after_offset > end_offset:
                return "", end_offset, end_offset
            if 0 <= after_offset <= end_offset:
                return output[after_offset:], after_offset, end_offset

        if tail_chars is not None and tail_chars > 0 and len(output) > tail_chars:
            return output[-tail_chars:], end_offset - tail_chars, end_offset
        return output, 0, end_offset

    def _get_completed_result_locked(
        self,
        terminal_id: str,
        *,
        mark_delivered: bool = False,
    ) -> dict[str, object] | None:
        completed_result = self.completed_commands.get(terminal_id)
        if completed_result is None:
            return None

        result = dict(completed_result.result)
        if completed_result.delivered:
            result["delta"] = ""
            return result

        if mark_delivered:
            completed_result.delivered = True
        return result

    def _resolve_completed_result_for_wait_locked(
        self,
        terminal_id: str | None,
    ) -> dict[str, object] | None:
        if terminal_id:
            return self._get_completed_result_locked(terminal_id, mark_delivered=True)

        active_commands = [
            active_command
            for active_command in self.active_commands.values()
            if active_command.is_alive()
        ]
        if active_commands:
            return None

        pending_completed_ids = [
            completed_terminal_id
            for completed_terminal_id, completed_result in self.completed_commands.items()
            if not completed_result.delivered
        ]
        if not pending_completed_ids:
            return None
        if len(pending_completed_ids) == 1:
            return self._get_completed_result_locked(
                pending_completed_ids[0],
                mark_delivered=True,
            )

        terminal_ids = ", ".join(sorted(pending_completed_ids))
        raise RuntimeError(
            "当前没有活动终端，但有多个已完成结果待领取，请显式传入 terminal_id。"
            f"可用 terminal_id: {terminal_ids}"
        )

    def _resolve_active_command_locked(
        self, terminal_id: str | None
    ) -> InteractiveCommand:
        if terminal_id:
            active_command = self.active_commands.get(terminal_id)
            if active_command is None or not active_command.is_alive():
                raise RuntimeError(f"未找到活动终端: {terminal_id}")
            return active_command

        active_commands = [
            active_command
            for active_command in self.active_commands.values()
            if active_command.is_alive()
        ]
        if not active_commands:
            raise RuntimeError("当前没有可交互的终端命令。")
        if len(active_commands) == 1:
            return active_commands[0]

        terminal_ids = ", ".join(
            sorted(active_command.terminal_id for active_command in active_commands)
        )
        raise RuntimeError(
            "当前存在多个活动终端，请显式传入 terminal_id。"
            f"可用 terminal_id: {terminal_ids}"
        )

    def _serialize_managed_process(
        self,
        managed_process: ManagedCommandProcess,
        active_command: InteractiveCommand | None,
        process_table: list[dict[str, Any]],
    ) -> dict[str, Any]:
        descendants = _collect_process_tree(managed_process.root_pid, process_table)
        is_running = active_command is not None and active_command.is_alive()

        if is_running:
            status = "running"
        elif descendants:
            status = "orphaned"
        elif managed_process.terminated_at is not None:
            status = "terminated"
        elif managed_process.last_return_code is not None:
            status = "completed"
        else:
            status = "unknown"

        return {
            "terminalId": managed_process.terminal_id,
            "command": managed_process.command,
            "rootPid": managed_process.root_pid,
            "status": status,
            "returnCode": managed_process.last_return_code,
            "startedAt": int(managed_process.started_at * 1000),
            "terminatedAt": int(managed_process.terminated_at * 1000)
            if managed_process.terminated_at is not None
            else None,
            "processCount": len(descendants),
            "processes": descendants,
        }

    def _build_input_request(
        self,
        active_command: InteractiveCommand,
        input_prompt: str | None,
    ) -> dict[str, object] | None:
        if input_prompt is None:
            return None
        return {
            "type": "text",
            "tool": "task_input",
            "task_id": active_command.terminal_id,
            "prompt": input_prompt,
            "command": active_command.command,
        }

    def _extract_prompt_text(self, full_output: str) -> str | None:
        tail_output = (
            full_output[-INTERACTIVE_PROMPT_TAIL_CHARS:]
            if len(full_output) > INTERACTIVE_PROMPT_TAIL_CHARS
            else full_output
        )
        lines = [line.strip() for line in tail_output.splitlines() if line.strip()]
        if not lines:
            return None

        last_line = lines[-1]
        normalized_last_line = last_line.lower()
        if normalized_last_line.endswith("?"):
            return last_line
        if normalized_last_line.endswith(":"):
            return last_line
        explicit_prompt_markers = [
            "yes/no",
            "[y/n]",
            "(y/n)",
            "(y/n/a)",
            "请输入",
            "是否",
            "请选择",
        ]
        if any(marker in normalized_last_line for marker in explicit_prompt_markers):
            return last_line
        if re.fullmatch(
            r"(press|hit)\s+(enter|return)(\s+to\s+\w+)?", normalized_last_line
        ):
            return last_line
        return None

    def _prompt_needs_idle_confirmation(self, full_output: str) -> bool:
        if full_output.endswith(("\n", "\r")):
            return False
        return True

    def _looks_like_prompt(self, full_output: str) -> bool:
        return self._extract_prompt_text(full_output) is not None

def _parse_timeout(timeout: object) -> int:
    if timeout is None:
        raise ValueError("timeout 为必填参数，单位秒。")
    try:
        parsed = int(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout 必须是正整数秒数。") from exc
    if parsed <= 0:
        raise ValueError("timeout 必须大于 0。")
    return parsed


def _parse_terminal_id(terminal_id: str = "") -> str | None:
    normalized = terminal_id.strip()
    return normalized or None


def _validate_command(command: str) -> None:
    normalized = command.lower()
    blocked_fragments = [
        "rm -rf",
        "rmdir /s",
        "del /s",
        ".git",
        "git push --force",
        "curl ",
        "| bash",
    ]
    for fragment in blocked_fragments:
        if fragment in normalized:
            raise ValueError(f"命令存在风险，已拒绝执行: {command}")


def _get_interactive_command_session(ctx: ToolContext) -> InteractiveCommandSession | None:
    session = ctx.metadata.get("interactive_command_session")
    if isinstance(session, InteractiveCommandSession):
        return session
    return None


def _format_one_shot_output(
    *,
    exit_code: int | None,
    stdout: str,
    stderr: str,
) -> str:
    return "\n".join(
        [
            f"exit_code: {exit_code}",
            "stdout:",
            stdout or "(empty)",
            "stderr:",
            stderr or "(empty)",
        ]
    )


def _run_one_shot_command(
    command: str,
    timeout: int,
    workspace: Path,
) -> dict[str, object]:
    process = subprocess.Popen(
        _build_powershell_utf8_command(command),
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_windows_process_kwargs(),
    )

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
            pass
        stdout = stdout.strip()
        stderr = stderr.strip()
        full_output = _format_one_shot_output(
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        return {
            "status": "timed_out",
            "exit_reason": "timeout",
            "command": command,
            "timeout": timeout,
            "return_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "full_output": full_output,
            "terminal_output": full_output,
            "terminated": True,
        }

    stdout = stdout.strip()
    stderr = stderr.strip()
    full_output = _format_one_shot_output(
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )
    return {
        "status": "completed" if process.returncode == 0 else "failed",
        "exit_reason": "completed" if process.returncode == 0 else "failed",
        "command": command,
        "return_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "full_output": full_output,
        "terminal_output": full_output,
    }


def run_command(
    ctx: ToolContext,
    content: str,
    timeout: int,
) -> dict[str, object]:
    """执行短命令。timeout 是硬边界；超时会终止整棵进程树。"""

    command = content.strip()
    parsed_timeout = _parse_timeout(timeout)
    if not command:
        raise ValueError("命令内容不能为空。")
    _validate_command(command)
    return _run_one_shot_command(command, parsed_timeout, Path(ctx.workspace or "."))


def start_task(
    ctx: ToolContext,
    content: str,
    timeout: int,
    task_id: str = "",
) -> dict[str, object]:
    """启动长任务或可交互命令；返回 task_id/terminal_id，用户可在终端面板介入。"""

    command = content.strip()
    parsed_timeout = _parse_timeout(timeout)
    parsed_task_id = _parse_terminal_id(task_id)
    if not command:
        raise ValueError("命令内容不能为空。")
    _validate_command(command)

    interactive_session = _get_interactive_command_session(ctx)
    if interactive_session is None:
        raise RuntimeError("当前会话没有可管理长任务的终端运行时。")

    result = interactive_session.start_command(
        command,
        parsed_timeout,
        terminal_id=parsed_task_id,
    )
    if isinstance(result, dict) and "terminal_id" in result:
        result["task_id"] = result["terminal_id"]
    return result


def _resolve_terminal_input(
    *,
    content: str,
    key: str,
    submit: bool,
) -> tuple[str, bool]:
    normalized_key = _normalize_terminal_key(key)
    if normalized_key:
        if normalized_key not in TERMINAL_KEY_INPUTS:
            supported = ", ".join(
                sorted({*TERMINAL_KEY_INPUTS.keys(), *TERMINAL_INTERRUPT_KEYS})
            )
            raise ValueError(f"不支持的终端按键: {normalized_key}。支持: {supported}")
        return TERMINAL_KEY_INPUTS[normalized_key], False

    resolved_content = _expand_terminal_inline_key_tokens(content)
    raw_content_key = _normalize_terminal_key(content)
    if raw_content_key in TERMINAL_INTERRUPT_KEYS:
        return "\x03", False
    if raw_content_key in TERMINAL_KEY_INPUTS:
        return TERMINAL_KEY_INPUTS[raw_content_key], False
    return resolved_content, _parse_bool_argument(submit)


def _send_task_input(
    ctx: ToolContext,
    timeout: int,
    content: str = "",
    key: str = "",
    terminal_id: str = "",
    submit: bool = True,
) -> dict[str, object]:
    """向当前正在运行的交互式终端命令发送输入或按键。"""

    parsed_timeout = _parse_timeout(timeout)
    parsed_terminal_id = _parse_terminal_id(terminal_id)
    interactive_session = _get_interactive_command_session(ctx)
    if interactive_session is None:
        raise RuntimeError("当前会话没有可交互的终端命令。")

    normalized_key = _normalize_terminal_key(key)
    raw_content_key = _normalize_terminal_key(content)
    if normalized_key in TERMINAL_INTERRUPT_KEYS or (
        not normalized_key and raw_content_key in TERMINAL_INTERRUPT_KEYS
    ):
        return interactive_session.interrupt_command(terminal_id=parsed_terminal_id)

    resolved_content, resolved_submit = _resolve_terminal_input(
        content=content,
        key=key,
        submit=submit,
    )
    if resolved_content == "":
        raise ValueError("content 或 key 不能为空。")

    return interactive_session.send_input(
        resolved_content,
        parsed_timeout,
        terminal_id=parsed_terminal_id,
        submit=resolved_submit,
    )


def _wait_for_task(
    ctx: ToolContext,
    timeout: int,
    terminal_id: str = "",
) -> dict[str, object]:
    """继续等待当前正在运行的终端命令，并返回新增输出或最终结果。"""

    parsed_timeout = _parse_timeout(timeout)
    parsed_terminal_id = _parse_terminal_id(terminal_id)
    interactive_session = _get_interactive_command_session(ctx)
    if interactive_session is None:
        raise RuntimeError("当前会话没有可等待的终端命令。")

    return interactive_session.wait_for_command(
        parsed_timeout,
        terminal_id=parsed_terminal_id,
    )


def task_input(
    ctx: ToolContext,
    timeout: int,
    content: str = "",
    key: str = "",
    task_id: str = "",
    submit: bool = True,
) -> dict[str, object]:
    """向 start_task 创建的长任务发送输入或按键。"""

    return _send_task_input(
        ctx,
        timeout=timeout,
        content=content,
        key=key,
        terminal_id=task_id,
        submit=submit,
    )


def task_wait(
    ctx: ToolContext,
    timeout: int,
    task_id: str = "",
) -> dict[str, object]:
    """等待 start_task 创建的长任务，并返回新增输出或最终结果。"""

    return _wait_for_task(ctx, timeout=timeout, terminal_id=task_id)


def task_stop(
    ctx: ToolContext,
    task_id: str = "",
) -> dict[str, Any]:
    """终止 start_task 创建的长任务。"""

    parsed_task_id = _parse_terminal_id(task_id)
    interactive_session = _get_interactive_command_session(ctx)
    if interactive_session is None:
        raise RuntimeError("当前会话没有可终止的长任务。")

    if parsed_task_id is None:
        active_processes = interactive_session.list_managed_processes(only_active=True)
        if len(active_processes) != 1:
            available = ", ".join(
                str(process.get("terminalId") or "")
                for process in active_processes
                if str(process.get("terminalId") or "").strip()
            )
            raise RuntimeError(
                "请显式传入 task_id。"
                + (f"可用 task_id: {available}" if available else "当前没有活动长任务。")
            )
        parsed_task_id = str(active_processes[0].get("terminalId") or "").strip()

    result = interactive_session.terminate_command(parsed_task_id)
    result["task_id"] = result.get("terminalId") or parsed_task_id
    return result

