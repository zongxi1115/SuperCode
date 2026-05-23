from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from agent.agent import CodingAgent
from agent.llm_client import OpenAICompatibleClient
from agent.schema import AgentResponse, AgentState, StepRecord, ToolCall
from agent.tools import BaseTool, ToolContext
from coding_agent.brain import CodeExplorationPromptBrain

INTERACTIVE_IDLE_SECONDS = 1.0
INTERACTIVE_POLL_SECONDS = 0.05
DEFAULT_IGNORED_DIR_NAMES = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
READ_FILE_MAX_OUTPUT_CHARS = 8000
LIST_FILE_DEFAULT_MAX_DEPTH = 2
LIST_FILE_MAX_RESULTS = 200
GLOB_MAX_RESULTS = 100
GREP_DEFAULT_LIMIT = 100
GREP_MAX_LIMIT = 300
CODE_EXPLORATION_DEFAULT_MAX_STEPS = 8
CODE_EXPLORATION_MAX_STEPS = 16
SUBAGENT_SUMMARY_MAX_CHARS = 6000
APPLY_PATCH_BEGIN = "*** Begin Patch"
APPLY_PATCH_END = "*** End Patch"
APPLY_PATCH_UPDATE_PREFIX = "*** Update File: "
APPLY_PATCH_EOF_MARKER = "*** End of File"


def _build_powershell_utf8_command(command: str) -> list[str]:
    bootstrap = (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$env:PYTHONIOENCODING = 'utf-8'; "
        "$env:PYTHONUTF8 = '1'; "
        "chcp 65001 > $null; "
    )
    return ["powershell", "-NoProfile", "-Command", f"{bootstrap}{command}"]


def _parse_bool_argument(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return bool(value)


def _parse_int_argument(
    value: object,
    *,
    field_name: str,
    minimum: int | None = None,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数。") from exc

    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} 必须大于等于 {minimum}。")
    return parsed


def _compact_text(value: str, limit: int) -> str:
    compact = " ".join(value.split()).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}\n\n... [truncated]"


def _should_respect_ignored_dirs(target: Path, include_ignored: bool) -> bool:
    return not include_ignored and target.name not in DEFAULT_IGNORED_DIR_NAMES


def _relative_posix_path(path: Path, workspace: Path) -> str:
    return str(path.relative_to(workspace)).replace("\\", "/")


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    """尽量终止整棵命令进程树。"""

    if process.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
        return

    process.kill()


def _kill_processes_by_pid(pids: list[int]) -> None:
    """按 PID 逐个强制终止，兼容父进程已退出但子进程残留的情况。"""

    unique_pids = sorted({pid for pid in pids if pid > 0}, reverse=True)
    if not unique_pids:
        return

    if sys.platform == "win32":
        for pid in unique_pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=5,
                    check=False,
                )
            except Exception:
                continue
        return

    for pid in unique_pids:
        try:
            subprocess.run(
                ["kill", "-9", str(pid)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except Exception:
            continue


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


@dataclass
class InteractiveCommand:
    """保存一条可继续输入的命令进程。"""

    terminal_id: str
    command: str
    process: subprocess.Popen[str]
    output: str = ""
    reported_length: int = 0
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
            while True:
                chunk = stream.read(1)
                if chunk == "":
                    break
                self.append_output(chunk)
        except Exception:
            self.append_output("\n[interactive command reader stopped unexpectedly]\n")

    def append_output(self, text: str) -> None:
        with self.lock:
            self.output += text
            self.last_output_at = time.monotonic()

    def mark_activity(self) -> None:
        with self.lock:
            self.last_output_at = time.monotonic()

    def snapshot_output(self) -> str:
        with self.lock:
            return self.output

    def snapshot_progress(self) -> tuple[str, int]:
        with self.lock:
            return self.output, self.reported_length

    def consume_delta(self) -> tuple[str, str]:
        with self.lock:
            full_output = self.output
            delta = full_output[self.reported_length :]
            self.reported_length = len(full_output)
        return delta, full_output

    def idle_for(self) -> float:
        with self.lock:
            return time.monotonic() - self.last_output_at

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def write_input(self, content: str) -> None:
        if self.process.stdin is None or not self.is_alive():
            raise RuntimeError("当前命令已经不能继续输入。")
        payload = content if content.endswith(("\n", "\r")) else f"{content}\n"
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
    idle_timeout: float = INTERACTIVE_IDLE_SECONDS
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
                    "或使用 terminal_input / terminal_wait 继续交互。"
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
    ) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            if terminal_id:
                completed_result = self._get_completed_result_locked(terminal_id)
                if completed_result is not None:
                    raise RuntimeError(f"终端 {terminal_id} 已完成，无法继续输入。")
            active_command = self._resolve_active_command_locked(terminal_id)

        active_command.write_input(content)
        return self._await_progress(active_command, timeout)

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
            return_on_idle=True,
            require_new_output_for_idle=True,
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

    def terminate_command(self, terminal_id: str) -> dict[str, Any]:
        with self.lock:
            active_command = self.active_commands.pop(terminal_id, None)
            managed_process = self.managed_processes.get(terminal_id)

        if managed_process is None:
            raise RuntimeError(f"未找到受管进程: {terminal_id}")

        if active_command is not None:
            active_command.close()
            managed_process.last_return_code = active_command.process.returncode

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
        )

    def _await_progress(
        self,
        active_command: InteractiveCommand,
        timeout: int,
        return_on_idle: bool = True,
        require_new_output_for_idle: bool = False,
        return_on_existing_prompt: bool = False,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        _, start_reported_length = active_command.snapshot_progress()

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

            full_output, _ = active_command.snapshot_progress()
            saw_new_output = len(full_output) > start_reported_length
            prompt_text = self._extract_prompt_text(full_output)
            if prompt_text is not None and (
                saw_new_output or return_on_existing_prompt
            ):
                return self._build_result(
                    active_command,
                    status="running",
                    exit_reason="awaiting_input",
                    input_prompt=prompt_text,
                )

            if return_on_idle and active_command.idle_for() >= self.idle_timeout:
                if saw_new_output or not require_new_output_for_idle:
                    return self._build_result(
                        active_command,
                        status="running",
                        exit_reason="idle",
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
        return dict(result)

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
            "tool": "terminal_input",
            "terminal_id": active_command.terminal_id,
            "prompt": input_prompt,
            "command": active_command.command,
        }

    def _extract_prompt_text(self, full_output: str) -> str | None:
        lines = [line.strip() for line in full_output.splitlines() if line.strip()]
        if not lines:
            return None

        last_line = lines[-1]
        normalized_last_line = last_line.lower()
        prompt_hints = [
            "select",
            "choose",
            "continue",
            "overwrite",
            "yes/no",
            "[y/n]",
            "(y/n)",
            "(y/n/a)",
            "enter",
            "input",
            "请输入",
            "是否",
            "请选择",
        ]
        if any(hint in normalized_last_line for hint in prompt_hints):
            return last_line
        if normalized_last_line.endswith("?"):
            return last_line
        if normalized_last_line.endswith(":"):
            return last_line
        return None

    def _looks_like_prompt(self, full_output: str) -> bool:
        return self._extract_prompt_text(full_output) is not None


class CodingBaseTool(BaseTool):
    """编码场景工具基类。"""

    def _request_backend_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            method=method,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "SuperCode/1.0",
            },
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"请求失败：HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"请求失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("请求超时。") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"返回了无法解析的 JSON：{raw_body[:300]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("返回格式不正确。")
        return parsed

    def _resolve_path(self, raw_path: str, context: ToolContext) -> Path:
        """把相对路径限制在当前工作区内。"""

        workspace = context.workspace.resolve()
        candidate = (workspace / raw_path).resolve()
        if workspace != candidate and workspace not in candidate.parents:
            raise ValueError(f"路径越界，不允许访问工作区外部: {raw_path}")
        return candidate

    def _read_text(self, target: Path) -> str:
        """统一按 UTF-8 读取文本。"""

        return target.read_text(encoding="utf-8")

    def _write_text(self, target: Path, content: str) -> None:
        """统一按 UTF-8 写回文本。"""

        target.write_text(content, encoding="utf-8")

    def _format_numbered_text(
        self,
        file_path: str,
        content: str,
        start_line: int = 1,
        metadata_lines: list[str] | None = None,
    ) -> str:
        """把文本格式化成带行号的输出。"""

        lines = content.splitlines()
        rendered = [f"# File: {file_path}"]
        if metadata_lines:
            rendered.extend(metadata_lines)
        if not lines:
            rendered.append(f"{start_line} | ")
            return "\n".join(rendered)

        for index, line in enumerate(lines, start=start_line):
            rendered.append(f"{index} | {line}")
        return "\n".join(rendered)


class GlobFileTool(CodingBaseTool):
    """按 glob 模式查找文件。"""

    name = "glob_file"
    description = (
        "按 glob 模式查找文件，参数：pattern 必填，search_path 可选默认当前目录，"
        "include_ignored 可选默认 false，limit 可选默认 100 且最大 100。"
        "适合先缩小文件范围，再决定是否 grep 或 read。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "search_path": {"type": "string"},
            "include_ignored": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        pattern = str(arguments["pattern"]).strip()
        if not pattern:
            raise ValueError("pattern 不能为空。")

        search_path = str(arguments.get("search_path", ".")).strip() or "."
        include_ignored = _parse_bool_argument(arguments.get("include_ignored", False))
        raw_limit = arguments.get("limit", GLOB_MAX_RESULTS)
        limit = min(
            _parse_int_argument(raw_limit, field_name="limit", minimum=1),
            GLOB_MAX_RESULTS,
        )

        target = self._resolve_path(search_path, context)
        if not target.exists():
            raise FileNotFoundError(f"搜索路径不存在: {search_path}")

        workspace = context.workspace.resolve()
        respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
        matches, truncated = self._collect_matches(
            target=target,
            workspace=workspace,
            search_root=target if target.is_dir() else target.parent,
            pattern=pattern,
            respect_ignored=respect_ignored,
            limit=limit,
        )

        if not matches:
            return f"未找到匹配文件: {pattern}"

        rendered = [
            f"# Search path: {search_path}",
            f"# Pattern: {pattern}",
            f"# Returned: {len(matches)}",
            f"# Limit: {limit}",
            f"# Truncated: {'true' if truncated else 'false'}",
            *matches,
        ]
        if truncated:
            rendered.append(
                "# Note: results truncated, please narrow pattern or search_path."
            )
        return "\n".join(rendered)

    def _collect_matches(
        self,
        *,
        target: Path,
        workspace: Path,
        search_root: Path,
        pattern: str,
        respect_ignored: bool,
        limit: int,
    ) -> tuple[list[str], bool]:
        if target.is_file():
            relative_from_root = _relative_posix_path(target, search_root)
            if fnmatch.fnmatch(relative_from_root, pattern) or fnmatch.fnmatch(
                target.name, pattern
            ):
                return [_relative_posix_path(target, workspace)], False
            return [], False

        matches: list[str] = []
        truncated = False
        for child in sorted(
            target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        ):
            if (
                respect_ignored
                and child.is_dir()
                and child.name in DEFAULT_IGNORED_DIR_NAMES
            ):
                continue

            if child.is_dir():
                nested_matches, nested_truncated = self._collect_matches(
                    target=child,
                    workspace=workspace,
                    search_root=search_root,
                    pattern=pattern,
                    respect_ignored=respect_ignored,
                    limit=limit - len(matches),
                )
                matches.extend(nested_matches)
                if nested_truncated or len(matches) >= limit:
                    truncated = True
                    break
                continue

            relative_from_root = _relative_posix_path(child, search_root)
            if not (
                fnmatch.fnmatch(relative_from_root, pattern)
                or fnmatch.fnmatch(child.name, pattern)
            ):
                continue
            matches.append(_relative_posix_path(child, workspace))
            if len(matches) >= limit:
                truncated = True
                break
        return matches, truncated


class ListFileTool(CodingBaseTool):
    """列举目录内的路径。"""

    name = "list_file"
    description = (
        "列举指定目录下的文件和目录路径，参数：path 可选，include_ignored 可选默认 false，"
        "max_depth 可选默认 2，limit 可选默认 200。默认只做浅层浏览，避免把整仓结构一次性塞进上下文。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "include_ignored": {"type": "boolean"},
            "max_depth": {"type": "integer"},
            "limit": {"type": "integer"},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        relative_path = str(arguments.get("path", "."))
        include_ignored = _parse_bool_argument(arguments.get("include_ignored", False))
        raw_max_depth = arguments.get("max_depth", LIST_FILE_DEFAULT_MAX_DEPTH)
        raw_limit = arguments.get("limit", LIST_FILE_MAX_RESULTS)
        max_depth = _parse_int_argument(
            raw_max_depth, field_name="max_depth", minimum=0
        )
        limit = min(
            _parse_int_argument(raw_limit, field_name="limit", minimum=1),
            LIST_FILE_MAX_RESULTS,
        )
        target = self._resolve_path(relative_path, context)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {relative_path}")

        workspace = context.workspace.resolve()
        rendered: list[str] = [f"# Path: {relative_path}"]
        respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
        if respect_ignored:
            rendered.append(
                "# Ignored: "
                + ", ".join(f"{name}/" for name in sorted(DEFAULT_IGNORED_DIR_NAMES))
            )
        rendered.append(f"# Max depth: {max_depth}")
        rendered.append(f"# Limit: {limit}")

        tree_lines, truncated = self._render_tree(
            target=target,
            workspace=workspace,
            respect_ignored=respect_ignored,
            current_depth=1,
            max_depth=max_depth,
            limit=limit,
        )
        rendered.append(f"# Truncated: {'true' if truncated else 'false'}")
        rendered.extend(tree_lines)

        if not tree_lines:
            rendered.append("(empty)")
        elif truncated:
            rendered.append(
                "# Note: list truncated, narrow path or increase max_depth thoughtfully."
            )
        return "\n".join(rendered)

    def _render_tree(
        self,
        target: Path,
        workspace: Path,
        respect_ignored: bool,
        current_depth: int,
        max_depth: int,
        limit: int,
    ) -> tuple[list[str], bool]:
        rendered: list[str] = []
        for child in sorted(
            target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        ):
            if len(rendered) >= limit:
                return rendered, True
            if (
                respect_ignored
                and child.is_dir()
                and child.name in DEFAULT_IGNORED_DIR_NAMES
            ):
                continue

            relative = _relative_posix_path(child, workspace)
            if child.is_dir():
                rendered.append(f"{relative}/")
                if len(rendered) >= limit:
                    return rendered, True
                if current_depth >= max_depth:
                    continue
                child_lines, child_truncated = self._render_tree(
                    target=child,
                    workspace=workspace,
                    respect_ignored=respect_ignored,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    limit=limit - len(rendered),
                )
                rendered.extend(child_lines)
                if child_truncated or len(rendered) >= limit:
                    return rendered, True
            else:
                rendered.append(relative)
        return rendered, False


class ReadFileTool(CodingBaseTool):
    """读取文件并返回带行号的内容。"""

    name = "read_file"
    description = (
        "读取文件内容，参数：filename 必填；offset、limit 可选，默认从文件开头读取；"
        "也兼容旧参数 start_line、end_line。返回内容带行号，并附带 requested/actual range、"
        "total_lines、total_chars、eof、truncated 元信息。"
        f"如果返回内容超过 {READ_FILE_MAX_OUTPUT_CHARS} 个字符，会自动截断到最大长度并提示继续分段读取。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["filename"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        filename = str(arguments["filename"])
        has_offset_limit = "offset" in arguments or "limit" in arguments
        has_line_range = "start_line" in arguments or "end_line" in arguments
        if has_offset_limit and has_line_range:
            raise ValueError(
                "read_file 不能同时混用 offset/limit 和 start_line/end_line。"
            )

        if has_offset_limit:
            offset = _parse_int_argument(
                arguments.get("offset", 0), field_name="offset", minimum=0
            )
            limit_raw = arguments.get("limit")
            limit = (
                _parse_int_argument(limit_raw, field_name="limit", minimum=1)
                if limit_raw is not None
                else None
            )
            start_line = offset + 1
            end_line = offset + limit if limit is not None else None
        else:
            start_line = _parse_int_argument(
                arguments.get("start_line", 1), field_name="start_line", minimum=1
            )
            end_line_raw = arguments.get("end_line")
            end_line = (
                _parse_int_argument(
                    end_line_raw, field_name="end_line", minimum=start_line
                )
                if end_line_raw is not None
                else None
            )
            offset = start_line - 1
            limit = (end_line - start_line + 1) if end_line is not None else None

        target = self._resolve_path(filename, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {filename}")

        text = self._read_text(target)
        total_chars = len(text)
        lines = text.splitlines()
        total_lines = len(lines)
        start_index = start_line - 1
        end_index = end_line if end_line is not None else len(lines)
        sliced = lines[start_index:end_index]
        actual_start_line = start_line if sliced else min(start_line, total_lines + 1)
        full_actual_end_line = (
            actual_start_line + len(sliced) - 1 if sliced else actual_start_line - 1
        )
        requested_end_line = end_line if end_line is not None else total_lines
        eof = full_actual_end_line >= total_lines if total_lines > 0 else True

        def build_metadata(
            *,
            actual_end_line: int,
            actual_limit: int,
            eof_flag: bool,
            truncated: bool,
        ) -> list[str]:
            metadata_lines = [
                f"# Requested offset: {offset}",
                f"# Requested limit: {limit if limit is not None else 'to EOF'}",
                f"# Requested lines: {start_line}-{requested_end_line}",
                f"# Actual offset: {max(actual_start_line - 1, 0)}",
                f"# Actual limit: {actual_limit}",
                f"# Actual lines: {actual_start_line}-{actual_end_line}",
                f"# Total lines: {total_lines}",
                f"# Total chars: {total_chars}",
                f"# EOF: {'true' if eof_flag else 'false'}",
                f"# Truncated: {'true' if truncated else 'false'}",
            ]
            if start_line > total_lines and total_lines > 0:
                metadata_lines.append(
                    "# Note: requested range starts beyond end of file."
                )
            if truncated:
                metadata_lines.append(
                    f"# Note: output truncated at {READ_FILE_MAX_OUTPUT_CHARS} chars; more content remains unread. "
                    "Use a narrower offset/limit or line range to continue reading."
                )
            return metadata_lines

        def render_with_limit(
            metadata_lines: list[str],
        ) -> tuple[str, bool, int]:
            rendered_lines = [f"# File: {filename}", *metadata_lines]
            current_length = len("\n".join(rendered_lines))
            if not sliced:
                rendered_lines.append(f"{actual_start_line} | ")
                return "\n".join(rendered_lines), False, actual_start_line - 1

            last_rendered_line = actual_start_line - 1
            truncated_output = False
            for line_number, line in enumerate(sliced, start=actual_start_line):
                prefix = f"{line_number} | "
                addition_length = 1 + len(prefix) + len(line)
                if current_length + addition_length <= READ_FILE_MAX_OUTPUT_CHARS:
                    rendered_lines.append(f"{prefix}{line}")
                    current_length += addition_length
                    last_rendered_line = line_number
                    continue

                remaining_for_content = (
                    READ_FILE_MAX_OUTPUT_CHARS - current_length - 1 - len(prefix)
                )
                if remaining_for_content > 0:
                    rendered_lines.append(f"{prefix}{line[:remaining_for_content]}")
                    last_rendered_line = line_number
                truncated_output = True
                break

            return "\n".join(rendered_lines), truncated_output, last_rendered_line

        metadata_lines = build_metadata(
            actual_end_line=full_actual_end_line,
            actual_limit=len(sliced),
            eof_flag=eof,
            truncated=False,
        )
        rendered, truncated_output, last_rendered_line = render_with_limit(
            metadata_lines
        )
        if not truncated_output:
            return rendered

        actual_end_line = last_rendered_line
        while True:
            truncated_metadata = build_metadata(
                actual_end_line=actual_end_line,
                actual_limit=max(actual_end_line - actual_start_line + 1, 0),
                eof_flag=False,
                truncated=True,
            )
            truncated_rendered, _, last_rendered_line = render_with_limit(
                truncated_metadata,
            )
            if last_rendered_line == actual_end_line:
                return truncated_rendered
            actual_end_line = last_rendered_line


class GrepFileTool(CodingBaseTool):
    """正则搜索文件内容。"""

    name = "grep_file"
    description = (
        "按正则搜索文件内容，优先使用 ripgrep。参数：regex 必填，search_path 可选默认当前目录，"
        "output_mode 可选 content/files_with_matches/count，glob 可选用于限制文件范围，"
        "file_type 可选用于限制语言类型，include_ignored 可选默认 false，limit 可选默认 100。"
    )
    supports_parallel = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "regex": {"type": "string"},
            "search_path": {"type": "string"},
            "output_mode": {"type": "string"},
            "glob": {"type": "string"},
            "file_type": {"type": "string"},
            "include_ignored": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": ["regex"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        regex = str(arguments["regex"]).strip()
        if not regex:
            raise ValueError("regex 不能为空。")

        search_path = str(arguments.get("search_path", ".")).strip() or "."
        output_mode = self._normalize_output_mode(
            arguments.get("output_mode", "content")
        )
        glob_pattern = str(arguments.get("glob", "")).strip()
        file_type = str(arguments.get("file_type", "")).strip()
        include_ignored = _parse_bool_argument(arguments.get("include_ignored", False))
        limit = min(
            _parse_int_argument(
                arguments.get("limit", GREP_DEFAULT_LIMIT),
                field_name="limit",
                minimum=1,
            ),
            GREP_MAX_LIMIT,
        )

        target = self._resolve_path(search_path, context)
        if not target.exists():
            raise FileNotFoundError(f"搜索路径不存在: {search_path}")

        respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
        if shutil.which("rg"):
            return self._run_with_ripgrep(
                regex=regex,
                target=target,
                search_path=search_path,
                context=context,
                output_mode=output_mode,
                glob_pattern=glob_pattern,
                file_type=file_type,
                respect_ignored=respect_ignored,
                limit=limit,
            )
        return self._run_python_fallback(
            regex=regex,
            target=target,
            context=context,
            output_mode=output_mode,
            glob_pattern=glob_pattern,
            file_type=file_type,
            respect_ignored=respect_ignored,
            limit=limit,
        )

    def _normalize_output_mode(self, raw_mode: object) -> str:
        mode = str(raw_mode or "content").strip().lower()
        allowed_modes = {"content", "files_with_matches", "count"}
        if mode not in allowed_modes:
            raise ValueError(f"output_mode 只支持: {', '.join(sorted(allowed_modes))}")
        return mode

    def _run_with_ripgrep(
        self,
        *,
        regex: str,
        target: Path,
        search_path: str,
        context: ToolContext,
        output_mode: str,
        glob_pattern: str,
        file_type: str,
        respect_ignored: bool,
        limit: int,
    ) -> str:
        workspace = context.workspace.resolve()
        relative_target = (
            _relative_posix_path(target, workspace) if target != workspace else "."
        )
        command = [
            "rg",
            "--hidden",
            "--no-ignore",
            "--color",
            "never",
            "--no-messages",
        ]
        if output_mode == "content":
            command.append("--line-number")
        elif output_mode == "files_with_matches":
            command.append("--files-with-matches")
        elif output_mode == "count":
            command.append("--count")

        if file_type:
            command.extend(["-t", file_type])
        if glob_pattern:
            command.extend(["--glob", glob_pattern])
        if respect_ignored:
            for ignored_dir in sorted(DEFAULT_IGNORED_DIR_NAMES):
                command.extend(["--glob", f"!{ignored_dir}/**"])
                command.extend(["--glob", f"!**/{ignored_dir}/**"])

        command.extend([regex, relative_target])

        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if result.returncode not in {0, 1}:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"grep_file 执行 ripgrep 失败：{stderr}")

        stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not stdout_lines:
            return f"未找到匹配项: {regex}"

        if output_mode == "content":
            return self._render_ripgrep_content(stdout_lines, regex=regex, limit=limit)
        if output_mode == "files_with_matches":
            return self._render_ripgrep_files(
                stdout_lines, regex=regex, limit=limit, search_path=search_path
            )
        return self._render_ripgrep_counts(
            stdout_lines, regex=regex, search_path=search_path
        )

    def _render_ripgrep_content(
        self, lines: list[str], *, regex: str, limit: int
    ) -> str:
        entries: list[tuple[str, int, str]] = []
        for row in lines:
            parts = row.split(":", 2)
            if len(parts) != 3:
                continue
            file_path, line_number, content = parts
            try:
                parsed_line_number = int(line_number)
            except ValueError:
                continue
            entries.append(
                (
                    self._normalize_ripgrep_relative_path(file_path),
                    parsed_line_number,
                    content,
                )
            )

        if not entries:
            return f"未找到匹配项: {regex}"
        entries.sort(key=lambda item: (item[0], item[1]))

        truncated = len(entries) > limit
        rendered: list[str] = []
        current_file = ""
        for file_path, parsed_line_number, content in entries[:limit]:
            if file_path != current_file:
                rendered.append(f"# File: {file_path}")
                current_file = file_path
            rendered.append(f"{parsed_line_number} | {content}")
        if truncated:
            rendered.append(
                f"# Note: output truncated at {limit} matches, narrow regex/glob/search_path."
            )
        return "\n".join(rendered)

    def _render_ripgrep_files(
        self,
        lines: list[str],
        *,
        regex: str,
        limit: int,
        search_path: str,
    ) -> str:
        normalized_files = sorted(
            self._normalize_ripgrep_relative_path(line)
            for line in lines
            if line.strip()
        )
        truncated = len(normalized_files) > limit
        files = normalized_files[:limit]
        rendered = [
            f"# Search path: {search_path}",
            f"# Regex: {regex}",
            f"# Returned files: {len(files)}",
            f"# Limit: {limit}",
            f"# Truncated: {'true' if truncated else 'false'}",
            *files,
        ]
        if truncated:
            rendered.append(
                "# Note: file results truncated, narrow regex/glob/search_path."
            )
        return "\n".join(rendered)

    def _render_ripgrep_counts(
        self,
        lines: list[str],
        *,
        regex: str,
        search_path: str,
    ) -> str:
        rendered = [
            f"# Search path: {search_path}",
            f"# Regex: {regex}",
        ]
        total_matches = 0
        rows: list[tuple[str, int]] = []
        for row in lines:
            parts = row.rsplit(":", 1)
            if len(parts) != 2:
                continue
            file_path, count_text = parts
            try:
                count = int(count_text)
            except ValueError:
                continue
            total_matches += count
            rows.append((self._normalize_ripgrep_relative_path(file_path), count))
        rendered.insert(2, f"# Total matches: {total_matches}")
        for file_path, count in sorted(rows, key=lambda item: item[0]):
            rendered.append(f"{file_path}: {count}")
        return "\n".join(rendered)

    def _run_python_fallback(
        self,
        *,
        regex: str,
        target: Path,
        context: ToolContext,
        output_mode: str,
        glob_pattern: str,
        file_type: str,
        respect_ignored: bool,
        limit: int,
    ) -> str:
        pattern = re.compile(regex, re.MULTILINE)
        workspace = context.workspace.resolve()
        if target.is_file():
            candidate_files = [target]
        else:
            candidate_files = self._collect_search_files(target, respect_ignored)

        filtered_files = [
            file_path
            for file_path in candidate_files
            if self._matches_glob(
                file_path, target if target.is_dir() else target.parent, glob_pattern
            )
            and self._matches_file_type(file_path, file_type)
        ]

        if output_mode == "files_with_matches":
            rendered_files: list[str] = []
            for file_path in filtered_files:
                match_line_numbers = self._find_matching_line_numbers(
                    pattern, self._safe_split_lines(file_path)
                )
                if not match_line_numbers:
                    continue
                rendered_files.append(_relative_posix_path(file_path, workspace))
                if len(rendered_files) >= limit:
                    break
            if not rendered_files:
                return f"未找到匹配项: {regex}"
            truncated = len(rendered_files) == limit
            rendered = [
                f"# Search path: {_relative_posix_path(target, workspace) if target != workspace else '.'}",
                f"# Regex: {regex}",
                f"# Returned files: {len(rendered_files)}",
                f"# Limit: {limit}",
                f"# Truncated: {'true' if truncated else 'false'}",
                *rendered_files,
            ]
            if truncated:
                rendered.append(
                    "# Note: file results truncated, narrow regex/glob/search_path."
                )
            return "\n".join(rendered)

        if output_mode == "count":
            rendered = [f"# Regex: {regex}"]
            total_matches = 0
            for file_path in filtered_files:
                match_line_numbers = self._find_matching_line_numbers(
                    pattern, self._safe_split_lines(file_path)
                )
                if not match_line_numbers:
                    continue
                total_matches += len(match_line_numbers)
                rendered.append(
                    f"{_relative_posix_path(file_path, workspace)}: {len(match_line_numbers)}"
                )
            if total_matches == 0:
                return f"未找到匹配项: {regex}"
            rendered.insert(1, f"# Total matches: {total_matches}")
            return "\n".join(rendered)

        rendered: list[str] = []
        matched_lines = 0
        for file_path in filtered_files:
            lines = self._safe_split_lines(file_path)
            match_line_numbers = self._find_matching_line_numbers(pattern, lines)
            if not match_line_numbers:
                continue

            rendered.append(f"# File: {_relative_posix_path(file_path, workspace)}")
            for line_number in match_line_numbers:
                rendered.append(f"{line_number} | {lines[line_number - 1]}")
                matched_lines += 1
                if matched_lines >= limit:
                    rendered.append(
                        f"# Note: output truncated at {limit} matches, narrow regex/glob/search_path."
                    )
                    return "\n".join(rendered)

        if not rendered:
            return f"未找到匹配项: {regex}"
        return "\n".join(rendered)

    def _collect_search_files(self, target: Path, respect_ignored: bool) -> list[Path]:
        candidate_files: list[Path] = []
        self._append_search_files(target, candidate_files, respect_ignored)
        return candidate_files

    def _append_search_files(
        self,
        current: Path,
        candidate_files: list[Path],
        respect_ignored: bool,
    ) -> None:
        for child in sorted(
            current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())
        ):
            if (
                respect_ignored
                and child.is_dir()
                and child.name in DEFAULT_IGNORED_DIR_NAMES
            ):
                continue
            if child.is_dir():
                self._append_search_files(child, candidate_files, respect_ignored)
                continue
            candidate_files.append(child)

    def _find_matching_line_numbers(
        self, pattern: re.Pattern[str], lines: list[str]
    ) -> list[int]:
        """找出命中的行号。"""

        matched_lines: list[int] = []
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                matched_lines.append(line_number)
        return matched_lines

    def _safe_split_lines(self, file_path: Path) -> list[str]:
        try:
            return self._read_text(file_path).splitlines()
        except UnicodeDecodeError:
            return []

    def _matches_glob(
        self, file_path: Path, search_root: Path, glob_pattern: str
    ) -> bool:
        if not glob_pattern:
            return True
        relative_path = _relative_posix_path(file_path, search_root)
        return fnmatch.fnmatch(relative_path, glob_pattern) or fnmatch.fnmatch(
            file_path.name, glob_pattern
        )

    def _matches_file_type(self, file_path: Path, file_type: str) -> bool:
        if not file_type:
            return True
        extension_map = {
            "py": {".py"},
            "ts": {".ts"},
            "vue": {".vue"},
        }
        allowed_extensions = extension_map.get(file_type.lower())
        if not allowed_extensions:
            return file_path.suffix.lower() == f".{file_type.lower()}"
        return file_path.suffix.lower() in allowed_extensions

    def _normalize_ripgrep_relative_path(self, file_path: str) -> str:
        normalized = file_path.replace("\\", "/").strip()
        if normalized.startswith("./"):
            return normalized[2:]
        return normalized


class DelegateCodeExplorationTool(CodingBaseTool):
    """委派只读代码探索子智能体。"""

    name = "delegate_code_exploration"
    description = (
        "委派一个只读代码探索子智能体查找相关模块、调用链、数据流和测试入口。"
        "参数：task 必填，focus_paths 可选路径数组，max_steps 可选默认 8。"
        "子智能体只允许 list_file、glob_file、read_file、grep_file，不会修改文件或执行命令。"
        "适合在主任务需要跨目录理解代码前使用；小范围已知文件请直接 read_file/grep_file。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string"},
            "focus_paths": {"type": "array", "items": {"type": "string"}},
            "max_steps": {"type": "integer"},
        },
        "required": ["task"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        task = str(arguments.get("task") or "").strip()
        if not task:
            raise ValueError("task 不能为空。")
        focus_paths = self._normalize_focus_paths(arguments.get("focus_paths"))
        max_steps = min(
            _parse_int_argument(
                arguments.get("max_steps", CODE_EXPLORATION_DEFAULT_MAX_STEPS),
                field_name="max_steps",
                minimum=1,
            ),
            CODE_EXPLORATION_MAX_STEPS,
        )

        snapshot = self._build_snapshot(
            task=task,
            focus_paths=focus_paths,
            status="running",
            steps=[],
        )
        self._emit_snapshot(context, snapshot)

        try:
            subagent = self._build_subagent(context, max_steps=max_steps)
            response = self._run_subagent(
                subagent,
                task=self._build_subagent_task(task, focus_paths),
            )
        except Exception as exc:  # noqa: BLE001 - 工具输出要把失败状态给 UI 展示
            snapshot = {
                **snapshot,
                "status": "error",
                "finalOutput": "",
                "error": str(exc),
            }
            self._emit_snapshot(context, snapshot)
            return {
                "status": "error",
                "task": task,
                "focus_paths": focus_paths,
                "error": str(exc),
                "data_part": {"type": "data-subagent-task", "data": snapshot},
            }

        final_snapshot = self._snapshot_from_response(
            response=response,
            task=task,
            focus_paths=focus_paths,
            max_steps=max_steps,
        )
        self._emit_snapshot(context, final_snapshot)
        return {
            "status": final_snapshot["status"],
            "task": task,
            "focus_paths": focus_paths,
            "files_read": final_snapshot["filesRead"],
            "commands_run": final_snapshot["commandsRun"],
            "findings": final_snapshot["findings"],
            "recommended_files": final_snapshot["recommendedFiles"],
            "final_output": final_snapshot["finalOutput"],
            "data_part": {"type": "data-subagent-task", "data": final_snapshot},
        }

    def _normalize_focus_paths(self, raw_value: object) -> list[str]:
        if raw_value is None:
            return []
        if not isinstance(raw_value, list):
            raise ValueError("focus_paths 必须是字符串数组。")
        paths: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_value:
            path = str(raw_path or "").strip().replace("\\", "/")
            if not path or path in seen:
                continue
            paths.append(path)
            seen.add(path)
            if len(paths) >= 12:
                break
        return paths

    def _build_subagent(self, context: ToolContext, *, max_steps: int) -> CodingAgent:
        factory = context.metadata.get("code_exploration_subagent_factory")
        if callable(factory):
            return factory(context, max_steps)

        client = context.metadata.get("llm_client")
        if not isinstance(client, OpenAICompatibleClient):
            raise RuntimeError("缺少 llm_client，无法启动代码探索子智能体。")

        return CodingAgent(
            brain=CodeExplorationPromptBrain(client, workspace=context.workspace),
            tools=build_code_exploration_tools(),
            workspace=context.workspace,
            max_steps=max_steps,
            tool_context_metadata={
                "include_thoughts_in_context": bool(
                    context.metadata.get("include_thoughts_in_context")
                ),
                "project_root": context.metadata.get("project_root"),
                "cancel_event": context.metadata.get("cancel_event"),
            },
        )

    def _build_subagent_task(self, task: str, focus_paths: list[str]) -> str:
        lines = [
            "请作为只读代码探索子智能体完成以下侦察任务。",
            "",
            f"任务：{task}",
        ]
        if focus_paths:
            lines.extend(
                [
                    "",
                    "优先关注路径：",
                    *[f"- {path}" for path in focus_paths],
                ]
            )
        lines.extend(
            [
                "",
                "请只返回摘要、关键路径、调用链/数据流、发现和建议下一步。",
            ]
        )
        return "\n".join(lines)

    def _run_subagent(self, subagent: CodingAgent, *, task: str) -> AgentResponse:
        state = AgentState(
            task="你是一个只读代码探索子智能体，请围绕主智能体委派的任务收集代码事实。",
            current_input=task,
            conversation_messages=[],
        )
        return subagent.run_turn(state)

    def _snapshot_from_response(
        self,
        *,
        response: AgentResponse,
        task: str,
        focus_paths: list[str],
        max_steps: int,
    ) -> dict[str, Any]:
        files_read = self._collect_files_read(response.steps)
        commands_run = self._collect_commands_run(response.steps)
        tool_names = self._collect_tool_names(response.steps)
        final_output = _truncate_text(response.final_output.strip(), SUBAGENT_SUMMARY_MAX_CHARS)
        findings = self._extract_findings(final_output)
        recommended_files = self._extract_recommended_files(final_output, files_read)
        status = "paused" if len(response.steps) >= max_steps and not final_output else "completed"
        steps = self._snapshot_steps(response.steps)
        current_thought = next(
            (step.thought for step in reversed(response.steps) if step.thought.strip()),
            "",
        )
        return self._build_snapshot(
            task=task,
            focus_paths=focus_paths,
            status=status,
            steps=steps,
            current_thought=current_thought,
            files_read=files_read,
            commands_run=commands_run,
            findings=findings,
            recommended_files=recommended_files,
            tool_names=tool_names,
            final_output=final_output,
        )

    def _build_snapshot(
        self,
        *,
        task: str,
        focus_paths: list[str],
        status: str,
        steps: list[dict[str, Any]],
        current_thought: str = "",
        files_read: list[str] | None = None,
        commands_run: list[str] | None = None,
        findings: list[str] | None = None,
        recommended_files: list[str] | None = None,
        tool_names: list[str] | None = None,
        final_output: str = "",
    ) -> dict[str, Any]:
        return {
            "id": f"code-exploration-{abs(hash((task, tuple(focus_paths))))}",
            "kind": "code_exploration",
            "title": "代码探索",
            "agentType": "code_exploration",
            "status": status,
            "task": task,
            "focusPaths": focus_paths,
            "currentThought": _compact_text(current_thought, 500),
            "steps": steps,
            "stepCount": len(steps),
            "filesRead": files_read or [],
            "changedFiles": [],
            "commandsRun": commands_run or [],
            "findings": findings or [],
            "recommendedFiles": recommended_files or [],
            "toolNames": tool_names or [],
            "finalOutput": final_output,
        }

    def _snapshot_steps(self, steps: list[StepRecord]) -> list[dict[str, Any]]:
        snapshot_steps: list[dict[str, Any]] = []
        for step in steps:
            tool_calls = self._step_tool_calls(step)
            name = ", ".join(tool.name for tool in tool_calls) if tool_calls else "final"
            has_error = any(
                result is not None and not result.success
                for result in self._step_tool_results(step)
            )
            snapshot_steps.append(
                {
                    "id": f"step-{step.index}",
                    "name": name,
                    "status": "error" if has_error else "completed",
                    "thought": _compact_text(step.thought, 300),
                }
            )
        return snapshot_steps

    def _collect_files_read(self, steps: list[StepRecord]) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name != "read_file":
                    continue
                filename = str(tool_call.arguments.get("filename") or "").strip()
                if filename and filename not in seen:
                    files.append(filename)
                    seen.add(filename)
        return files

    def _collect_commands_run(self, steps: list[StepRecord]) -> list[str]:
        commands: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name not in {"execute", "excecute"}:
                    continue
                command = str(
                    tool_call.arguments.get("content")
                    or tool_call.arguments.get("command")
                    or ""
                ).strip()
                if command and command not in seen:
                    commands.append(command)
                    seen.add(command)
        return commands

    def _collect_tool_names(self, steps: list[StepRecord]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name not in seen:
                    names.append(tool_call.name)
                    seen.add(tool_call.name)
        return names

    def _extract_findings(self, final_output: str) -> list[str]:
        findings: list[str] = []
        for raw_line in final_output.splitlines():
            line = raw_line.strip().lstrip("-*0123456789.、) ")
            if not line or line.startswith("#"):
                continue
            findings.append(_compact_text(line, 220))
            if len(findings) >= 6:
                break
        return findings

    def _extract_recommended_files(
        self,
        final_output: str,
        files_read: list[str],
    ) -> list[str]:
        recommended: list[str] = []
        seen: set[str] = set()
        path_pattern = re.compile(r"[\w@./\\-]+\.[A-Za-z0-9]{1,8}")
        for candidate in [*path_pattern.findall(final_output), *files_read]:
            normalized = candidate.strip("`'\".,:;()[]{}").replace("\\", "/")
            if not normalized or normalized in seen:
                continue
            recommended.append(normalized)
            seen.add(normalized)
            if len(recommended) >= 8:
                break
        return recommended

    def _step_tool_calls(self, step: StepRecord) -> list[ToolCall]:
        if step.tool_calls:
            return step.tool_calls
        return [step.tool_call] if step.tool_call is not None else []

    def _step_tool_results(self, step: StepRecord) -> list[Any]:
        if step.tool_results:
            return step.tool_results
        return [step.tool_result] if step.tool_result is not None else []

    def _emit_snapshot(self, context: ToolContext, snapshot: dict[str, Any]) -> None:
        emitter = context.metadata.get("runtime_event_emitter")
        if not callable(emitter):
            return
        try:
            emitter("data-subagent-task", {"data": snapshot})
        except TypeError:
            emitter("data-subagent-task", snapshot)


class WriteFileTool(CodingBaseTool):
    """创建新文件。"""

    name = "write_file"
    description = "创建并写入新文件，参数：filename、content。若文件已存在会报错。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["filename", "content"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        filename = str(arguments["filename"])
        content = str(arguments.get("content", ""))
        target = self._resolve_path(filename, context)
        if target.exists():
            raise FileExistsError(f"文件已存在，禁止覆写: {filename}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已创建文件: {filename}"


class ApplyPatchTool(CodingBaseTool):
    """基于行号区间修改已有文件。"""

    name = "apply_patch"
    description = (
        "基于起止行号替换文件内容，参数：filename、start_line、end_line、new_content。"
        "包含 start_line 和 end_line，即 [start_line, end_line] 会被替换。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "new_content": {"type": "string"},
        },
        "required": ["filename", "start_line", "end_line", "new_content"],
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        filename = str(arguments["filename"])
        start_line = int(arguments["start_line"])
        end_line = int(arguments["end_line"])
        new_content = str(arguments.get("new_content", ""))

        if start_line < 1 or end_line < 1:
            raise ValueError("start_line 和 end_line 必须 >= 1")
        if start_line > end_line + 1:
            raise ValueError("start_line 不能大于 end_line + 1")

        target = self._resolve_path(filename, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {filename}")

        original_text = self._read_text(target)
        had_trailing_newline = original_text.endswith("\n")

        lines = original_text.splitlines()
        total_lines = len(lines)

        if start_line > total_lines + 1:
            raise ValueError(
                f"start_line ({start_line}) 超出文件总行数 ({total_lines})"
            )

        new_lines = new_content.splitlines()

        # 0-indexed slicing
        prefix = lines[: start_line - 1]
        suffix = lines[end_line:] if end_line <= total_lines else []

        updated_lines = prefix + new_lines + suffix
        updated_text = "\n".join(updated_lines)

        if had_trailing_newline and (updated_text or original_text):
            updated_text += "\n"

        self._write_text(target, updated_text)

        return {
            "summary": f"已修改文件 {filename} 的第 {start_line} 到 {end_line} 行。",
            "files": [filename],
        }


class ReplaceFileTool(CodingBaseTool):
    """局部替换文件内容。"""

    name = "replace_file"
    description = "替换已有文件中的一段内容，参数：filename、old_content、new_content。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "old_content": {"type": "string"},
            "new_content": {"type": "string"},
        },
        "required": ["filename", "old_content", "new_content"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        filename = str(arguments["filename"])
        old_content = str(arguments["old_content"])
        new_content = str(arguments.get("new_content", ""))
        target = self._resolve_path(filename, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {filename}")

        content = self._read_text(target)
        occurrences = content.count(old_content)
        if occurrences == 0:
            raise ValueError("未找到要替换的 old_content。")
        if occurrences > 1:
            raise ValueError("old_content 匹配到多处内容，请提供更精确的上下文。")

        updated = content.replace(old_content, new_content, 1)
        target.write_text(updated, encoding="utf-8")
        return f"已更新文件: {filename}"


def delete_file_in_workspace(raw_path: str, workspace: Path) -> str:
    """在工作区内安全删除单个文件。"""

    workspace_root = workspace.resolve()
    candidate = (workspace_root / raw_path).resolve()
    if workspace_root != candidate and workspace_root not in candidate.parents:
        raise ValueError(f"路径越界，不允许删除工作区外部文件: {raw_path}")
    if not candidate.exists():
        raise FileNotFoundError(f"文件不存在: {raw_path}")
    if not candidate.is_file():
        raise IsADirectoryError(f"目标不是文件: {raw_path}")

    candidate.unlink()
    return f"已删除文件: {raw_path}"


class DeleteFileTool(CodingBaseTool):
    """删除文件，但先返回确认请求。"""

    name = "delete_file"
    description = "删除文件，参数：filename。执行前需要用户确认。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
        },
        "required": ["filename"],
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        filename = str(arguments["filename"])
        target = self._resolve_path(filename, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {filename}")

        return {
            "requires_confirmation": True,
            "filename": filename,
            "absolute_path": str(target),
            "message": f"确认删除文件 {filename}？",
        }


class ExecuteTool(CodingBaseTool):
    """执行命令。"""

    name = "execute"
    description = (
        "在工作区内执行命令，参数：content、timeout（必填，单位秒）、terminal_id（可选）。"
        "若命令持续运行，会返回 terminal_id 和当前输出，后续可用 terminal_input / terminal_wait 按 terminal_id 继续交互。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "timeout": {"type": "integer"},
            "terminal_id": {"type": "string"},
        },
        "required": ["content", "timeout"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        command = str(arguments["content"]).strip()
        timeout = self._parse_timeout(arguments)
        terminal_id = self._parse_terminal_id(arguments)
        if not command:
            raise ValueError("命令内容不能为空。")
        self._validate_command(command)

        interactive_session = self._get_interactive_command_session(context)
        if interactive_session is not None:
            return interactive_session.start_command(
                command, timeout, terminal_id=terminal_id
            )

        return self._run_one_shot_command(command, timeout, context.workspace)

    def _parse_timeout(self, arguments: dict[str, object]) -> int:
        """解析并校验超时时间。"""

        raw_timeout = arguments.get("timeout")
        if raw_timeout is None:
            raise ValueError("timeout 为必填参数，单位秒。")

        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout 必须是正整数秒数。") from exc

        if timeout <= 0:
            raise ValueError("timeout 必须大于 0。")
        return timeout

    def _parse_terminal_id(self, arguments: dict[str, object]) -> str | None:
        raw_terminal_id = str(arguments.get("terminal_id", "")).strip()
        return raw_terminal_id or None

    def _validate_command(self, command: str) -> None:
        """阻止明显危险的命令。"""

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

    def _get_interactive_command_session(
        self,
        context: ToolContext,
    ) -> InteractiveCommandSession | None:
        session = context.metadata.get("interactive_command_session")
        if isinstance(session, InteractiveCommandSession):
            return session
        return None

    def _run_one_shot_command(
        self,
        command: str,
        timeout: int,
        workspace: Path,
    ) -> str:
        process = subprocess.Popen(
            _build_powershell_utf8_command(command),
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise TimeoutError(f"命令执行超时（>{timeout} 秒）: {command}") from exc

        stdout = stdout.strip()
        stderr = stderr.strip()
        lines = [
            f"exit_code: {process.returncode}",
            "stdout:",
            stdout or "(empty)",
            "stderr:",
            stderr or "(empty)",
        ]
        return "\n".join(lines)


class TerminalInputTool(CodingBaseTool):
    """给当前交互式命令继续输入。"""

    name = "terminal_input"
    description = (
        "向当前正在运行的交互式终端命令发送输入，参数：content、timeout（必填，单位秒）、terminal_id（可选）。"
        "如果同时存在多个活动终端，terminal_id 为必填；如果 content 不带换行，会自动补一个回车。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "timeout": {"type": "integer"},
            "terminal_id": {"type": "string"},
        },
        "required": ["content", "timeout"],
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        content = str(arguments.get("content", ""))
        timeout = self._parse_timeout(arguments)
        terminal_id = self._parse_terminal_id(arguments)
        if content == "":
            raise ValueError("content 不能为空。")

        interactive_session = context.metadata.get("interactive_command_session")
        if not isinstance(interactive_session, InteractiveCommandSession):
            raise RuntimeError("当前会话没有可交互的终端命令。")

        return interactive_session.send_input(content, timeout, terminal_id=terminal_id)

    def _parse_timeout(self, arguments: dict[str, object]) -> int:
        raw_timeout = arguments.get("timeout")
        if raw_timeout is None:
            raise ValueError("timeout 为必填参数，单位秒。")

        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout 必须是正整数秒数。") from exc

        if timeout <= 0:
            raise ValueError("timeout 必须大于 0。")
        return timeout

    def _parse_terminal_id(self, arguments: dict[str, object]) -> str | None:
        raw_terminal_id = str(arguments.get("terminal_id", "")).strip()
        return raw_terminal_id or None


class TerminalWaitTool(CodingBaseTool):
    """继续等待当前交互式命令。"""

    name = "terminal_wait"
    description = (
        "继续等待当前正在运行的终端命令，参数：timeout（必填，单位秒）、terminal_id（可选）。"
        "如果终端已在本次等待前完成，会返回缓存的最终结果。"
        "如果同时存在多个活动终端，terminal_id 为必填。用于后台安装、构建或下载仍在继续时收集后续输出。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "timeout": {"type": "integer"},
            "terminal_id": {"type": "string"},
        },
        "required": ["timeout"],
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        timeout = self._parse_timeout(arguments)
        terminal_id = self._parse_terminal_id(arguments)
        interactive_session = context.metadata.get("interactive_command_session")
        if not isinstance(interactive_session, InteractiveCommandSession):
            raise RuntimeError("当前会话没有可等待的终端命令。")

        return interactive_session.wait_for_command(timeout, terminal_id=terminal_id)

    def _parse_timeout(self, arguments: dict[str, object]) -> int:
        raw_timeout = arguments.get("timeout")
        if raw_timeout is None:
            raise ValueError("timeout 为必填参数，单位秒。")

        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout 必须是正整数秒数。") from exc

        if timeout <= 0:
            raise ValueError("timeout 必须大于 0。")
        return timeout

    def _parse_terminal_id(self, arguments: dict[str, object]) -> str | None:
        raw_terminal_id = str(arguments.get("terminal_id", "")).strip()
        return raw_terminal_id or None


class ExcecuteTool(ExecuteTool):
    """兼容用户给出的工具名拼写。"""

    name = "excecute"
    description = (
        "在工作区内执行命令，参数：content、timeout（必填，单位秒）。与 execute 同义。"
    )


class OpenBrowserTool(CodingBaseTool):
    """为前端内置浏览器生成可访问的预览地址。"""

    name = "open_browser"
    description = (
        "打开内置浏览器预览。参数二选一："
        "1) url：网络地址，例如 http://localhost:3000、https://example.com、localhost:5173；"
        "2) path：本地文件或目录路径，支持工作区内相对路径和绝对路径。"
        "如果 path 指向目录，会自动寻找其中的 index.html 或 index.htm。"
        "不要把本地文件路径塞进 url，也不要把网络地址塞进 path。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "path": {"type": "string"},
            "target": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, str]:
        raw_path = str(arguments.get("path") or "").strip()
        raw_url = str(arguments.get("url") or "").strip()
        raw_target = str(arguments.get("target") or "").strip()

        if raw_path and raw_url:
            raise ValueError(
                "path 和 url 只能传一个。path 用于本地文件，url 用于网络地址。"
            )
        if raw_url:
            selected_kind = "url"
            selected_target = raw_url
        elif raw_path:
            selected_kind = "path"
            selected_target = raw_path
        elif raw_target:
            selected_kind = "url" if self._looks_like_url(raw_target) else "path"
            selected_target = raw_target
        else:
            raise ValueError(
                "必须提供 url 或 path。url 用于网络地址，path 用于本地文件或目录。"
            )

        backend_base_url = str(
            context.metadata.get("backend_base_url", "http://localhost:8000")
        ).rstrip("/")
        if selected_kind == "url":
            resolved_url = self._normalize_url(selected_target)
            return {
                "target": selected_target,
                "resolved_url": resolved_url,
                "source_type": "network_url",
            }

        session_id = str(context.metadata.get("session_id", "")).strip()
        if not session_id:
            raise RuntimeError("当前会话缺少 session_id，无法生成预览地址。")

        resolved_path = self._resolve_path(selected_target, context)
        preview_target = self._resolve_preview_target(resolved_path)
        workspace = context.workspace.resolve()
        try:
            relative_preview_path = preview_target.relative_to(workspace).as_posix()
        except ValueError as exc:
            raise ValueError(f"预览路径不在工作区内: {selected_target}") from exc

        encoded_preview_path = quote(relative_preview_path, safe="/")
        return {
            "target": selected_target,
            "absolute_path": str(preview_target),
            "resolved_url": f"{backend_base_url}/api/sessions/{session_id}/preview/{encoded_preview_path}",
            "source_type": "local_file",
        }

    def _looks_like_url(self, value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https", "file"}:
            return True
        if value.startswith(("localhost:", "127.0.0.1:", "0.0.0.0:", "[::1]:")):
            return True
        return bool(re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(:\d+)?([/?#].*)?$", value))

    def _normalize_url(self, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https", "file"}:
            return value
        return f"http://{value}"

    def _resolve_preview_target(self, target: Path) -> Path:
        if target.is_dir():
            for entry_name in ("index.html", "index.htm"):
                candidate = target / entry_name
                if candidate.exists() and candidate.is_file():
                    return candidate
            raise FileNotFoundError(f"目录下未找到可预览入口文件: {target}")
        if not target.exists():
            raise FileNotFoundError(f"预览目标不存在: {target}")
        if not target.is_file():
            raise ValueError(f"预览目标不是文件: {target}")
        return target


class GreepToolCompat(GrepFileTool):
    """保留一个兼容类名，避免以后手滑拼错导入。"""


class ReadCurrentPlanTool(CodingBaseTool):
    """读取当前会话里最新的计划草案。"""

    name = "read_current_plan"
    description = (
        "读取当前会话中最新的计划草案/计划正文。"
        "当用户在前端手动编辑过计划后，用它获取最新 markdown 和结构化内容。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        del arguments
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip(
            "/"
        )
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError(
                "缺少 backend_base_url 或 session_id，无法读取当前计划。"
            )

        payload = self._request_backend_json(
            method="GET",
            url=f"{backend_base_url}/api/sessions/{session_id}/plan-draft/current",
        )

        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise RuntimeError("当前会话没有可读取的计划草案。")
        return {
            "plan": plan,
            "planState": payload.get("planState"),
        }


class CreateTaskTool(CodingBaseTool):
    name = "create_task"
    description = (
        "创建一个结构化 task。参数：title、summary、steps。"
        "steps 是数组，每项都需要 title 和 summary。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["title", "summary"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "summary", "steps"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip(
            "/"
        )
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError("缺少 backend_base_url 或 session_id，无法创建 task。")

        title = str(arguments.get("title") or "").strip()
        summary = str(arguments.get("summary") or "").strip()
        raw_steps = arguments.get("steps")
        if not title:
            raise ValueError("title 不能为空。")
        if not summary:
            raise ValueError("summary 不能为空。")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("steps 不能为空。")

        steps: list[dict[str, str]] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                raise ValueError("steps 里的每一项都必须是对象。")
            step_title = str(raw_step.get("title") or "").strip()
            step_summary = str(raw_step.get("summary") or "").strip()
            if not step_title or not step_summary:
                raise ValueError("每个 step 都必须包含 title 和 summary。")
            steps.append({"title": step_title, "summary": step_summary})

        payload = self._request_backend_json(
            method="POST",
            url=f"{backend_base_url}/api/sessions/{session_id}/tasks",
            payload={"title": title, "summary": summary, "steps": steps},
        )
        return {
            "task_id": payload.get("task_id"),
            "step_ids": payload.get("step_ids"),
            "task": payload.get("task"),
            "planState": payload.get("planState"),
            "planSteps": payload.get("planSteps"),
        }


class FinishTaskTool(CodingBaseTool):
    name = "finish_task"
    description = "完成当前正在执行的 step。参数：step_id。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "step_id": {"type": "string"},
        },
        "required": ["step_id"],
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip(
            "/"
        )
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError("缺少 backend_base_url 或 session_id，无法完成 step。")

        step_id = str(arguments.get("step_id") or "").strip()
        if not step_id:
            raise ValueError("step_id 不能为空。")

        payload = self._request_backend_json(
            method="POST",
            url=f"{backend_base_url}/api/sessions/{session_id}/tasks/finish",
            payload={"step_id": step_id},
        )
        return {
            "task_id": payload.get("task_id"),
            "step_id": payload.get("step_id"),
            "finished": payload.get("finished"),
            "next_step_id": payload.get("next_step_id"),
            "planState": payload.get("planState"),
            "planSteps": payload.get("planSteps"),
        }


class GetTaskStatusTool(CodingBaseTool):
    name = "get_task_status"
    description = "获取当前会话里的 task 状态。参数：task_id 可选。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, Any]:
        backend_base_url = str(context.metadata.get("backend_base_url") or "").rstrip(
            "/"
        )
        session_id = str(context.metadata.get("session_id") or "").strip()
        if not backend_base_url or not session_id:
            raise RuntimeError(
                "缺少 backend_base_url 或 session_id，无法读取 task 状态。"
            )

        task_id = str(arguments.get("task_id") or "").strip()
        query = f"?{urlencode({'task_id': task_id})}" if task_id else ""
        payload = self._request_backend_json(
            method="GET",
            url=f"{backend_base_url}/api/sessions/{session_id}/tasks/status{query}",
        )
        return {
            "active_task_id": payload.get("active_task_id"),
            "active_step_id": payload.get("active_step_id"),
            "active_task": payload.get("active_task"),
            "tasks": payload.get("tasks"),
            "planState": payload.get("planState"),
            "planSteps": payload.get("planSteps"),
        }


class GitCommitTool(CodingBaseTool):
    name = "git_commit"
    description = (
        "暂存所有变更并创建 git 提交，参数：message（必填，提交信息）。"
        "执行前需要用户确认。会在工作区根目录执行 git add -A && git commit。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
        },
        "required": ["message"],
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        message = str(arguments["message"]).strip()
        if not message:
            raise ValueError("提交信息不能为空。")

        workspace = context.workspace.resolve()
        if not (workspace / ".git").exists():
            raise RuntimeError("当前工作区不是 git 仓库，请先初始化。")

        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if not status_result.stdout.strip():
            return {
                "requires_confirmation": False,
                "message": "没有待提交的变更。",
                "has_changes": False,
            }

        changed_files = [
            line.strip()
            for line in status_result.stdout.strip().splitlines()
            if line.strip()
        ]

        return {
            "requires_confirmation": True,
            "message": f"确认提交 {len(changed_files)} 个文件变更？提交信息：{message}",
            "commit_message": message,
            "changed_files": changed_files[:30],
            "has_changes": True,
        }


def execute_git_commit(message: str, workspace: Path) -> str:
    workspace_root = workspace.resolve()

    add_result = subprocess.run(
        ["git", "add", "-A"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if add_result.returncode != 0:
        raise RuntimeError(f"git add 失败：{add_result.stderr.strip()}")

    safe_message = message.replace('"', '\\"')
    commit_result = subprocess.run(
        ["git", "commit", "-m", safe_message],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if commit_result.returncode != 0:
        stderr = commit_result.stderr.strip()
        if "nothing to commit" in stderr or "nothing to commit" in commit_result.stdout:
            return "没有待提交的变更。"
        raise RuntimeError(f"git commit 失败：{stderr}")

    return commit_result.stdout.strip() or "提交成功。"


class GitLogTool(CodingBaseTool):
    name = "git_log"
    description = (
        "查看 git 提交历史，参数：count（可选，默认 20，最大 100）。"
        "返回提交哈希、作者、时间和提交信息。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
        },
        "additionalProperties": False,
    }

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        raw_count = arguments.get("count", 20)
        count = min(max(int(raw_count), 1), 100)

        workspace = context.workspace.resolve()
        if not (workspace / ".git").exists():
            raise RuntimeError("当前工作区不是 git 仓库。")

        result = subprocess.run(
            ["git", "log", f"-{count}", "--pretty=format:%h|%an|%ai|%s"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git log 失败：{result.stderr.strip()}")

        lines = result.stdout.strip().splitlines()
        if not lines or not lines[0].strip():
            return "暂无提交历史。"

        rendered = ["# Git Log"]
        for line in lines:
            parts = line.split("|", 3)
            if len(parts) >= 4:
                rendered.append(f"{parts[0]} {parts[3]}")
                rendered.append(f"  作者: {parts[1]}  时间: {parts[2]}")
            else:
                rendered.append(line)
        return "\n".join(rendered)


class GitTagTool(CodingBaseTool):
    name = "git_tag"
    description = (
        "管理 git 标签（版本），参数：tag（可选，标签名）、message（可选，标签注释）、"
        "list（可选，默认 false，设为 true 列出已有标签）。"
        "创建标签需要用户确认。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "tag": {"type": "string"},
            "message": {"type": "string"},
            "list": {"type": "boolean"},
        },
        "additionalProperties": False,
    }

    def run(
        self, arguments: dict[str, object], context: ToolContext
    ) -> dict[str, object]:
        list_tags = _parse_bool_argument(arguments.get("list", False))
        workspace = context.workspace.resolve()

        if not (workspace / ".git").exists():
            raise RuntimeError("当前工作区不是 git 仓库。")

        if list_tags:
            result = subprocess.run(
                ["git", "tag", "-l", "--sort=-creatordate"],
                cwd=workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            tags = [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]
            return {"tags": tags, "count": len(tags)}

        tag_name = str(arguments.get("tag", "")).strip()
        if not tag_name:
            raise ValueError("创建标签必须提供 tag 名称。")

        tag_message = str(arguments.get("message", "")).strip() or f"Release {tag_name}"

        return {
            "requires_confirmation": True,
            "message": f"确认创建标签 {tag_name}？注释：{tag_message}",
            "tag": tag_name,
            "tag_message": tag_message,
        }


def execute_git_tag(tag_name: str, tag_message: str, workspace: Path) -> str:
    workspace_root = workspace.resolve()

    result = subprocess.run(
        ["git", "tag", "-a", tag_name, "-m", tag_message],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "already exists" in stderr:
            raise RuntimeError(f"标签 {tag_name} 已存在。")
        raise RuntimeError(f"创建标签失败：{stderr}")

    return f"已创建标签: {tag_name}"


def init_git_repo(workspace: Path) -> str:
    workspace_root = workspace.resolve()
    if (workspace_root / ".git").exists():
        return "已有 git 仓库。"

    init_result = subprocess.run(
        ["git", "init"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    if init_result.returncode != 0:
        raise RuntimeError(f"git init 失败：{init_result.stderr.strip()}")

    gitignore_content = (
        "node_modules/\n"
        "dist/\n"
        "build/\n"
        ".next/\n"
        ".nuxt/\n"
        ".venv/\n"
        "venv/\n"
        "__pycache__/\n"
        ".pytest_cache/\n"
        ".turbo/\n"
        "*.pyc\n"
        ".env\n"
        ".env.*\n"
        "!.env.example\n"
        "*.log\n"
        ".DS_Store\n"
        "Thumbs.db\n"
        "*.swp\n"
        "*.swo\n"
        "*~\n"
        ".idea/\n"
        ".vscode/\n"
        "coverage/\n"
    )
    gitignore_path = workspace_root / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(gitignore_content, encoding="utf-8")

    add_result = subprocess.run(
        ["git", "add", "-A"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    commit_result = subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )

    return f"已初始化 git 仓库并创建 .gitignore。"


def build_coding_tools() -> list[BaseTool]:
    """构造编码智能体默认工具集。"""

    return [
        ListFileTool(),
        GlobFileTool(),
        ReadFileTool(),
        GrepFileTool(),
        DelegateCodeExplorationTool(),
        CreateTaskTool(),
        GetTaskStatusTool(),
        FinishTaskTool(),
        ApplyPatchTool(),
        WriteFileTool(),
        ReplaceFileTool(),
        DeleteFileTool(),
        TerminalInputTool(),
        TerminalWaitTool(),
        OpenBrowserTool(),
        ReadCurrentPlanTool(),
        ExcecuteTool(),
        ExecuteTool(),
        GitCommitTool(),
        GitLogTool(),
        GitTagTool(),
    ]


def build_code_exploration_tools() -> list[BaseTool]:
    """构造代码探索子智能体的只读工具集。"""

    return [
        ListFileTool(),
        GlobFileTool(),
        ReadFileTool(),
        GrepFileTool(),
    ]
