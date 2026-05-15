from __future__ import annotations

import re
import subprocess
from pathlib import Path

from agent.tools import BaseTool, ToolContext


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
    description = "列举指定目录下的文件和目录路径，参数：path 可选。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        relative_path = str(arguments.get("path", "."))
        target = self._resolve_path(relative_path, context)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {relative_path}")

        workspace = context.workspace.resolve()
        rendered: list[str] = [f"# Path: {relative_path}"]
        for child in sorted(target.rglob("*")):
            relative = str(child.relative_to(workspace)).replace("\\", "/")
            if child.is_dir():
                rendered.append(f"{relative}/")
            else:
                rendered.append(relative)

        if len(rendered) == 1:
            rendered.append("(empty)")
        return "\n".join(rendered)


class ReadFileTool(CodingBaseTool):
    """读取文件并返回带行号的内容。"""

    name = "read_file"
    description = "读取文件内容，可传 filename、start_line、end_line，返回内容带行号。"

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
        return self._format_numbered_text(filename, "\n".join(sliced), start_line=start_line)


class GrepFileTool(CodingBaseTool):
    """正则搜索文件内容。"""

    name = "grep_file"
    description = (
        "按正则搜索文件内容，参数：regex 必填，context_line 可选默认 30，"
        "search_path 可选默认当前目录，返回带行号的上下文。"
    )

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        regex = str(arguments["regex"])
        context_line = int(arguments.get("context_line", 30))
        search_path = str(arguments.get("search_path", "."))
        if context_line < 0:
            raise ValueError("context_line 不能小于 0。")

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

            merged_ranges = self._merge_line_ranges(match_line_numbers, context_line, len(lines))
            relative_path = str(file_path.relative_to(workspace)).replace("\\", "/")
            rendered.append(f"# File: {relative_path}")
            for range_start, range_end in merged_ranges:
                for line_number in range(range_start, range_end + 1):
                    rendered.append(f"{line_number} | {lines[line_number - 1]}")
                rendered.append("---")

        if not rendered:
            return f"未找到匹配项: {regex}"

        if rendered[-1] == "---":
            rendered.pop()
        return "\n".join(rendered)

    def _find_matching_line_numbers(self, pattern: re.Pattern[str], lines: list[str]) -> list[int]:
        """找出命中的行号。"""

        matched_lines: list[int] = []
        for line_number, line in enumerate(lines, start=1):
            if pattern.search(line):
                matched_lines.append(line_number)
        return matched_lines

    def _merge_line_ranges(
        self,
        match_lines: list[int],
        context_line: int,
        max_line: int,
    ) -> list[tuple[int, int]]:
        """把多个命中行的上下文区间合并。"""

        ranges: list[tuple[int, int]] = []
        for line_number in match_lines:
            start = max(1, line_number - context_line)
            end = min(max_line, line_number + context_line)
            if not ranges:
                ranges.append((start, end))
                continue

            last_start, last_end = ranges[-1]
            if start <= last_end + 1:
                ranges[-1] = (last_start, max(last_end, end))
            else:
                ranges.append((start, end))
        return ranges


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
    description = "在工作区内执行命令，参数：content。会阻止危险命令。"

    def run(self, arguments: dict[str, object], context: ToolContext) -> str:
        command = str(arguments["content"]).strip()
        if not command:
            raise ValueError("命令内容不能为空。")
        self._validate_command(command)

        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                command,
            ],
            cwd=context.workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        lines = [
            f"exit_code: {completed.returncode}",
            "stdout:",
            stdout or "(empty)",
            "stderr:",
            stderr or "(empty)",
        ]
        return "\n".join(lines)

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
            "pnpm build",
            "npm run build",
        ]
        for fragment in blocked_fragments:
            if fragment in normalized:
                raise ValueError(f"命令存在风险，已拒绝执行: {command}")


class ExcecuteTool(ExecuteTool):
    """兼容用户给出的工具名拼写。"""

    name = "excecute"
    description = "在工作区内执行命令，参数：content。与 execute 同义。"


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
        ExcecuteTool(),
        ExecuteTool(),
    ]
