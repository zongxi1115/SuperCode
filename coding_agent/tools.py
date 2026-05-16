from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from agent.tools import BaseTool, ToolContext

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
READ_FILE_MAX_OUTPUT_CHARS = 3500


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


@dataclass
class InteractiveCommand:
    """保存一条可继续输入的命令进程。"""

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
class InteractiveCommandSession:
    """管理当前会话里可继续输入的一条命令。"""

    workspace: Path
    idle_timeout: float = INTERACTIVE_IDLE_SECONDS
    active_command: InteractiveCommand | None = field(default=None, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def start_command(self, command: str, timeout: int) -> dict[str, object]:
        with self.lock:
            self._clear_finished_locked()
            if self.active_command is not None and self.active_command.is_alive():
                raise RuntimeError("已有终端命令正在运行，请先使用 terminal_input 继续交互。")

            process = self._spawn_process(command)
            self.active_command = InteractiveCommand(command=command, process=process)
            active_command = self.active_command

        return self._await_progress(active_command, timeout)

    def send_input(self, content: str, timeout: int) -> dict[str, object]:
        with self.lock:
            active_command = self.active_command

        if active_command is None or not active_command.is_alive():
            raise RuntimeError("当前没有可继续输入的终端命令。")

        active_command.write_input(content)
        return self._await_progress(active_command, timeout)

    def wait_for_command(self, timeout: int) -> dict[str, object]:
        with self.lock:
            active_command = self.active_command

        if active_command is None or not active_command.is_alive():
            raise RuntimeError("当前没有可等待的终端命令。")

        active_command.mark_activity()
        return self._await_progress(active_command, timeout, return_on_idle=False)

    def close(self) -> None:
        with self.lock:
            active_command = self.active_command
            self.active_command = None

        if active_command is not None:
            active_command.close()

    def _spawn_process(self, command: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                command,
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

    def _await_progress(
        self,
        active_command: InteractiveCommand,
        timeout: int,
        return_on_idle: bool = True,
    ) -> dict[str, object]:
        deadline = time.monotonic() + timeout

        while True:
            if not active_command.is_alive():
                active_command.wait_for_readers()
                result = self._build_result(active_command, status="completed")
                active_command.close_streams()
                with self.lock:
                    if self.active_command is active_command:
                        self.active_command = None
                return result

            if return_on_idle and active_command.idle_for() >= self.idle_timeout:
                return self._build_result(active_command, status="running")

            if time.monotonic() >= deadline:
                return self._build_result(active_command, status="running")

            time.sleep(INTERACTIVE_POLL_SECONDS)

    def _build_result(
        self,
        active_command: InteractiveCommand,
        status: str,
    ) -> dict[str, object]:
        delta, full_output = active_command.consume_delta()
        awaiting_input = status == "running" and self._looks_like_prompt(full_output)
        return {
            "status": status,
            "command": active_command.command,
            "delta": delta,
            "full_output": full_output,
            "return_code": active_command.process.returncode,
            "awaiting_input": awaiting_input,
        }

    def _clear_finished_locked(self) -> None:
        if self.active_command is not None and not self.active_command.is_alive():
            self.active_command = None

    def _looks_like_prompt(self, full_output: str) -> bool:
        lines = [line.strip().lower() for line in full_output.splitlines() if line.strip()]
        if not lines:
            return False

        last_line = lines[-1]
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
        if any(hint in last_line for hint in prompt_hints):
            return True
        if last_line.endswith("?"):
            return True
        return last_line.endswith(":")


class CodingBaseTool(BaseTool):
    """编码场景工具基类。"""

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

    def _format_numbered_text(
        self,
        file_path: str,
        content: str,
        start_line: int = 1,
    ) -> str:
        """把文本格式化成带行号的输出。"""

        lines = content.splitlines()
        rendered = [f"# File: {file_path}"]
        if not lines:
            rendered.append(f"{start_line} | ")
            return "\n".join(rendered)

        for index, line in enumerate(lines, start=start_line):
            rendered.append(f"{index} | {line}")
        return "\n".join(rendered)


class ListFileTool(CodingBaseTool):
    """列举目录内的路径。"""

    name = "list_file"
    description = (
        "列举指定目录下的文件和目录路径，参数：path 可选，include_ignored 可选默认 false。"
        "默认会跳过 node_modules、.git、dist、build、__pycache__ 等生成目录。"
    )
    supports_parallel = True

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        relative_path = str(arguments.get("path", "."))
        include_ignored = self._parse_bool(arguments.get("include_ignored", False))
        target = self._resolve_path(relative_path, context)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {relative_path}")

        workspace = context.workspace.resolve()
        rendered: list[str] = [f"# Path: {relative_path}"]
        respect_ignored = not include_ignored and target.name not in DEFAULT_IGNORED_DIR_NAMES
        if respect_ignored:
            rendered.append(
                "# Ignored: "
                + ", ".join(f"{name}/" for name in sorted(DEFAULT_IGNORED_DIR_NAMES))
            )

        rendered.extend(self._render_tree(target, workspace, respect_ignored))

        if len(rendered) == 1 or (len(rendered) == 2 and rendered[1].startswith("# Ignored:")):
            rendered.append("(empty)")
        return "\n".join(rendered)

    def _render_tree(
        self,
        target: Path,
        workspace: Path,
        respect_ignored: bool,
    ) -> list[str]:
        rendered: list[str] = []
        for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if respect_ignored and child.is_dir() and child.name in DEFAULT_IGNORED_DIR_NAMES:
                continue

            relative = str(child.relative_to(workspace)).replace("\\", "/")
            if child.is_dir():
                rendered.append(f"{relative}/")
                rendered.extend(self._render_tree(child, workspace, respect_ignored))
            else:
                rendered.append(relative)
        return rendered

    def _parse_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off", ""}:
                return False
        return bool(value)


class ReadFileTool(CodingBaseTool):
    """读取文件并返回带行号的内容。"""

    name = "read_file"
    description = (
        "读取文件内容，可传 filename、start_line、end_line，返回内容带行号。"
        "如果返回内容超过 1600 个字符会直接报错，此时必须缩小范围，改用 start_line/end_line 分段读取。"
    )
    supports_parallel = True

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        filename = str(arguments["filename"])
        start_line = int(arguments.get("start_line", 1))
        end_line_raw = arguments.get("end_line")
        end_line = int(end_line_raw) if end_line_raw is not None else None

        target = self._resolve_path(filename, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {filename}")
        if start_line <= 0:
            raise ValueError("start_line 必须大于等于 1。")
        if end_line is not None and end_line < start_line:
            raise ValueError("end_line 不能小于 start_line。")

        lines = self._read_text(target).splitlines()
        start_index = start_line - 1
        end_index = end_line if end_line is not None else len(lines)
        sliced = lines[start_index:end_index]
        rendered = self._format_numbered_text(filename, "\n".join(sliced), start_line=start_line)
        if len(rendered) > READ_FILE_MAX_OUTPUT_CHARS:
            raise ValueError(
                f"本次 read_file 返回内容过长，已超过 {READ_FILE_MAX_OUTPUT_CHARS} 字符。"
                "请缩小读取范围并传入更精确的 start_line/end_line。"
            )
        return rendered


class GrepFileTool(CodingBaseTool):
    """正则搜索文件内容。"""

    name = "grep_file"
    description = (
        "按正则搜索文件内容，参数：regex 必填，search_path 可选默认当前目录，"
        "只返回命中的文件、行号和对应行内容。"
    )
    supports_parallel = True

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        regex = str(arguments["regex"])
        search_path = str(arguments.get("search_path", "."))

        target = self._resolve_path(search_path, context)
        if not target.exists():
            raise FileNotFoundError(f"搜索目录不存在: {search_path}")

        pattern = re.compile(regex, re.MULTILINE)
        workspace = context.workspace.resolve()
        rendered: list[str] = []

        for file_path in sorted(path for path in target.rglob("*") if path.is_file()):
            try:
                content = self._read_text(file_path)
            except UnicodeDecodeError:
                continue
            lines = content.splitlines()
            match_line_numbers = self._find_matching_line_numbers(pattern, lines)
            if not match_line_numbers:
                continue

            relative_path = str(file_path.relative_to(workspace)).replace("\\", "/")
            rendered.append(f"# File: {relative_path}")
            for line_number in match_line_numbers:
                rendered.append(f"{line_number} | {lines[line_number - 1]}")

        if not rendered:
            return f"未找到匹配项: {regex}"

        return "\n".join(rendered)

    def _find_matching_line_numbers(self, pattern: re.Pattern[str], lines: list[str]) -> list[int]:
        """找出命中的行号。"""

        matched_lines: list[int] = []
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                matched_lines.append(line_number)
        return matched_lines

class WriteFileTool(CodingBaseTool):
    """创建新文件。"""

    name = "write_file"
    description = "创建并写入新文件，参数：filename、content。若文件已存在会报错。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        filename = str(arguments["filename"])
        content = str(arguments.get("content", ""))
        target = self._resolve_path(filename, context)
        if target.exists():
            raise FileExistsError(f"文件已存在，禁止覆写: {filename}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已创建文件: {filename}"


class ReplaceFileTool(CodingBaseTool):
    """局部替换文件内容。"""

    name = "replace_file"
    description = "替换已有文件中的一段内容，参数：filename、old_content、new_content。"

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


class ExecuteTool(CodingBaseTool):
    """执行命令。"""

    name = "execute"
    description = "在工作区内执行命令，参数：content、timeout（必填，单位秒）。若命令持续运行，会返回当前输出并允许后续用 terminal_input 继续输入。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        command = str(arguments["content"]).strip()
        timeout = self._parse_timeout(arguments)
        if not command:
            raise ValueError("命令内容不能为空。")
        self._validate_command(command)

        interactive_session = self._get_interactive_command_session(context)
        if interactive_session is not None:
            return interactive_session.start_command(command, timeout)

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
            "| bash"
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
            [
                "powershell",
                "-NoProfile",
                "-Command",
                command,
            ],
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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
    description = "向当前正在运行的交互式终端命令发送输入，参数：content、timeout（必填，单位秒）。如果 content 不带换行，会自动补一个回车。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, object]:
        content = str(arguments.get("content", ""))
        timeout = self._parse_timeout(arguments)
        if content == "":
            raise ValueError("content 不能为空。")

        interactive_session = context.metadata.get("interactive_command_session")
        if not isinstance(interactive_session, InteractiveCommandSession):
            raise RuntimeError("当前会话没有可交互的终端命令。")

        return interactive_session.send_input(content, timeout)

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


class TerminalWaitTool(CodingBaseTool):
    """继续等待当前交互式命令。"""

    name = "terminal_wait"
    description = "继续等待当前正在运行的终端命令，参数：timeout（必填，单位秒）。用于后台安装、构建或下载仍在继续时收集后续输出。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, object]:
        timeout = self._parse_timeout(arguments)
        interactive_session = context.metadata.get("interactive_command_session")
        if not isinstance(interactive_session, InteractiveCommandSession):
            raise RuntimeError("当前会话没有可等待的终端命令。")

        return interactive_session.wait_for_command(timeout)

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


class ExcecuteTool(ExecuteTool):
    """兼容用户给出的工具名拼写。"""

    name = "excecute"
    description = "在工作区内执行命令，参数：content、timeout（必填，单位秒）。与 execute 同义。"


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

    def run(self, arguments: dict[str, object], context: ToolContext) -> dict[str, str]:
        raw_path = str(arguments.get("path") or "").strip()
        raw_url = str(arguments.get("url") or "").strip()
        raw_target = str(arguments.get("target") or "").strip()

        if raw_path and raw_url:
            raise ValueError("path 和 url 只能传一个。path 用于本地文件，url 用于网络地址。")
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
            raise ValueError("必须提供 url 或 path。url 用于网络地址，path 用于本地文件或目录。")

        session_id = str(context.metadata.get("session_id", "")).strip()
        backend_base_url = str(context.metadata.get("backend_base_url", "http://localhost:8000")).rstrip("/")
        if not session_id:
            raise RuntimeError("当前会话缺少 session_id，无法生成预览地址。")

        if selected_kind == "url":
            resolved_url = self._normalize_url(selected_target)
            return {
                "target": selected_target,
                "resolved_url": resolved_url,
                "source_type": "network_url",
            }

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
        if parsed.scheme:
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


def build_coding_tools() -> list[BaseTool]:
    """构造编码智能体默认工具集。"""

    return [
        ListFileTool(),
        ReadFileTool(),
        GrepFileTool(),
        WriteFileTool(),
        ReplaceFileTool(),
        TerminalInputTool(),
        TerminalWaitTool(),
        OpenBrowserTool(),
        ExcecuteTool(),
        ExecuteTool(),
    ]
