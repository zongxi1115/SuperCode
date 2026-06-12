from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zonix.tools import ToolContext

from .tool_common import (
    DEFAULT_IGNORED_DIR_NAMES,
    GLOB_MAX_RESULTS,
    GREP_DEFAULT_LIMIT,
    GREP_MAX_LIMIT,
    LIST_FILE_DEFAULT_MAX_DEPTH,
    LIST_FILE_MAX_RESULTS,
    READ_FILE_MAX_OUTPUT_CHARS,
    _hidden_windows_process_kwargs,
    _parse_int_argument,
    _relative_posix_path,
    _should_respect_ignored_dirs,
)


@dataclass(slots=True)
class WorkspaceFiles:
    workspace: Path

    @classmethod
    def from_context(cls, ctx: ToolContext) -> "WorkspaceFiles":
        return cls(Path(ctx.workspace or ".").resolve())

    def resolve_path(self, raw_path: str) -> Path:
        candidate = (self.workspace / raw_path).resolve()
        if self.workspace != candidate and self.workspace not in candidate.parents:
            raise ValueError(f"路径越界，不允许访问工作区外部: {raw_path}")
        return candidate

    def read_text(self, target: Path) -> str:
        return target.read_text(encoding="utf-8")

    def write_text(self, target: Path, content: str) -> None:
        target.write_text(content, encoding="utf-8")

    def format_numbered_text(
        self,
        file_path: str,
        content: str,
        start_line: int = 1,
        metadata_lines: list[str] | None = None,
    ) -> str:
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


def glob_file(
    ctx: ToolContext,
    pattern: str,
    search_path: str = ".",
    include_ignored: bool = False,
    limit: int = GLOB_MAX_RESULTS,
) -> str:
    """按 glob 模式查找文件，适合先缩小文件范围，再决定是否 grep 或 read。"""

    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern 不能为空。")

    files = WorkspaceFiles.from_context(ctx)
    search_path = search_path.strip() or "."
    limit = min(_parse_int_argument(limit, field_name="limit", minimum=1), GLOB_MAX_RESULTS)
    target = files.resolve_path(search_path)
    if not target.exists():
        raise FileNotFoundError(f"搜索路径不存在: {search_path}")

    respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
    matches, truncated = _collect_glob_matches(
        target=target,
        workspace=files.workspace,
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
        rendered.append("# Note: results truncated, please narrow pattern or search_path.")
    return "\n".join(rendered)


def _collect_glob_matches(
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
        if fnmatch.fnmatch(relative_from_root, pattern) or fnmatch.fnmatch(target.name, pattern):
            return [_relative_posix_path(target, workspace)], False
        return [], False

    matches: list[str] = []
    truncated = False
    for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if respect_ignored and child.is_dir() and child.name in DEFAULT_IGNORED_DIR_NAMES:
            continue
        if child.is_dir():
            nested_matches, nested_truncated = _collect_glob_matches(
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
        if not (fnmatch.fnmatch(relative_from_root, pattern) or fnmatch.fnmatch(child.name, pattern)):
            continue
        matches.append(_relative_posix_path(child, workspace))
        if len(matches) >= limit:
            truncated = True
            break
    return matches, truncated


def list_file(
    ctx: ToolContext,
    path: str = ".",
    include_ignored: bool = False,
    max_depth: int = LIST_FILE_DEFAULT_MAX_DEPTH,
    limit: int = LIST_FILE_MAX_RESULTS,
) -> str:
    """列举目录内的文件和目录路径，默认浅层浏览，避免把整仓结构一次性塞进上下文。"""

    files = WorkspaceFiles.from_context(ctx)
    relative_path = path or "."
    max_depth = _parse_int_argument(max_depth, field_name="max_depth", minimum=0)
    limit = min(_parse_int_argument(limit, field_name="limit", minimum=1), LIST_FILE_MAX_RESULTS)
    target = files.resolve_path(relative_path)
    if not target.exists():
        raise FileNotFoundError(f"目录不存在: {relative_path}")
    if not target.is_dir():
        raise NotADirectoryError(f"目标不是目录: {relative_path}")

    rendered: list[str] = [f"# Path: {relative_path}"]
    respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
    if respect_ignored:
        rendered.append("# Ignored: " + ", ".join(f"{name}/" for name in sorted(DEFAULT_IGNORED_DIR_NAMES)))
    rendered.append(f"# Max depth: {max_depth}")
    rendered.append(f"# Limit: {limit}")

    tree_lines, truncated = _render_tree(
        target=target,
        workspace=files.workspace,
        respect_ignored=respect_ignored,
        current_depth=1,
        max_depth=max_depth,
        limit=limit,
    )
    rendered.append(f"# Truncated: {'true' if truncated else 'false'}")
    rendered.extend(tree_lines or ["(empty)"])
    if tree_lines and truncated:
        rendered.append("# Note: list truncated, narrow path or increase max_depth thoughtfully.")
    return "\n".join(rendered)


def _render_tree(
    *,
    target: Path,
    workspace: Path,
    respect_ignored: bool,
    current_depth: int,
    max_depth: int,
    limit: int,
) -> tuple[list[str], bool]:
    rendered: list[str] = []
    for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if len(rendered) >= limit:
            return rendered, True
        if respect_ignored and child.is_dir() and child.name in DEFAULT_IGNORED_DIR_NAMES:
            continue

        relative = _relative_posix_path(child, workspace)
        if child.is_dir():
            rendered.append(f"{relative}/")
            if len(rendered) >= limit:
                return rendered, True
            if current_depth >= max_depth:
                continue
            child_lines, child_truncated = _render_tree(
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


def read_file(
    ctx: ToolContext,
    filename: str,
    offset: int | None = None,
    limit: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """读取文件内容，返回带行号文本和范围元信息；编辑前优先一次读足相关上下文。"""

    files = WorkspaceFiles.from_context(ctx)
    target = files.resolve_path(filename)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not target.is_file():
        raise IsADirectoryError(f"目标不是文件: {filename}")

    offset, limit, start_line, end_line = _normalize_range_arguments(
        offset=offset,
        limit=limit,
        start_line=start_line,
        end_line=end_line,
    )
    text = files.read_text(target)
    total_chars = len(text)
    lines = text.splitlines()
    total_lines = len(lines)
    start_index = start_line - 1
    end_index = end_line if end_line is not None else len(lines)
    sliced = lines[start_index:end_index]
    actual_start_line = start_line if sliced else min(start_line, total_lines + 1)
    full_actual_end_line = actual_start_line + len(sliced) - 1 if sliced else actual_start_line - 1
    requested_end_line = end_line if end_line is not None else total_lines
    eof = full_actual_end_line >= total_lines if total_lines > 0 else True

    def build_metadata(*, actual_end_line: int, actual_limit: int, eof_flag: bool, truncated: bool) -> list[str]:
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
            metadata_lines.append("# Note: requested range starts beyond end of file.")
        if truncated:
            metadata_lines.append(
                f"# Note: output truncated at {READ_FILE_MAX_OUTPUT_CHARS} chars; more content remains unread. "
                "Use a narrower offset/limit or line range to continue reading."
            )
        return metadata_lines

    def render_with_limit(metadata_lines: list[str]) -> tuple[str, bool, int]:
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

            remaining_for_content = READ_FILE_MAX_OUTPUT_CHARS - current_length - 1 - len(prefix)
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
    rendered, truncated_output, last_rendered_line = render_with_limit(metadata_lines)
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
        truncated_rendered, _, last_rendered_line = render_with_limit(truncated_metadata)
        if last_rendered_line == actual_end_line:
            return truncated_rendered
        actual_end_line = last_rendered_line


def _normalize_range_arguments(
    *,
    offset: int | None,
    limit: int | None,
    start_line: int | None,
    end_line: int | None,
) -> tuple[int, int | None, int, int | None]:
    if offset is not None and offset < 0:
        raise ValueError("offset 必须大于等于 0。")
    if limit is not None and limit < 1:
        limit = None
    if start_line is not None and start_line < 1:
        raise ValueError("start_line 必须大于等于 1。")
    if end_line is not None and end_line < 1:
        raise ValueError("end_line 必须大于等于 1。")

    has_offset_range = offset is not None or limit is not None
    has_line_range = start_line is not None or end_line is not None
    resolved_offset = offset or 0
    offset_start_line = resolved_offset + 1
    offset_end_line = resolved_offset + limit if limit is not None else None
    line_start_line = start_line or 1

    if has_line_range and end_line is not None and end_line < line_start_line:
        raise ValueError("end_line 必须大于等于 start_line。")
    if has_offset_range and has_line_range:
        ranges_match = (
            limit is not None
            and offset_start_line == line_start_line
            and offset_end_line == end_line
        )
        if not ranges_match:
            raise ValueError("read_file 不能同时混用 offset/limit 和 start_line/end_line。")
    if has_line_range:
        return line_start_line - 1, (
            end_line - line_start_line + 1 if end_line is not None else None
        ), line_start_line, end_line
    return resolved_offset, limit, offset_start_line, offset_end_line


def grep_file(
    ctx: ToolContext,
    regex: str,
    search_path: str = ".",
    output_mode: str = "content",
    glob: str = "",
    file_type: str = "",
    include_ignored: bool = False,
    limit: int = GREP_DEFAULT_LIMIT,
) -> str:
    """按正则搜索文件内容，优先使用 ripgrep，失败时回退到 Python 搜索。"""

    regex = regex.strip()
    if not regex:
        raise ValueError("regex 不能为空。")
    output_mode = _normalize_output_mode(output_mode)
    limit = min(_parse_int_argument(limit, field_name="limit", minimum=1), GREP_MAX_LIMIT)

    files = WorkspaceFiles.from_context(ctx)
    search_path = search_path.strip() or "."
    target = files.resolve_path(search_path)
    if not target.exists():
        raise FileNotFoundError(f"搜索路径不存在: {search_path}")

    respect_ignored = _should_respect_ignored_dirs(target, include_ignored)
    if shutil.which("rg"):
        try:
            return _run_ripgrep(
                regex=regex,
                target=target,
                workspace=files.workspace,
                output_mode=output_mode,
                glob_pattern=glob.strip(),
                file_type=file_type.strip(),
                respect_ignored=respect_ignored,
                limit=limit,
                search_path=search_path,
            )
        except RuntimeError:
            pass

    return _run_python_grep(
        regex=regex,
        target=target,
        workspace=files.workspace,
        output_mode=output_mode,
        glob_pattern=glob.strip(),
        file_type=file_type.strip(),
        respect_ignored=respect_ignored,
        limit=limit,
    )


def _normalize_output_mode(value: str) -> str:
    output_mode = (value or "content").strip()
    valid_modes = {"content", "files_with_matches", "count"}
    if output_mode not in valid_modes:
        raise ValueError(f"output_mode 只支持: {', '.join(sorted(valid_modes))}")
    return output_mode


def _run_ripgrep(
    *,
    regex: str,
    target: Path,
    workspace: Path,
    output_mode: str,
    glob_pattern: str,
    file_type: str,
    respect_ignored: bool,
    limit: int,
    search_path: str,
) -> str:
    relative_target = "." if target == workspace else _relative_posix_path(target, workspace)
    command = ["rg", "--color", "never", "--no-messages"]
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
        **_hidden_windows_process_kwargs(),
    )
    if result.returncode not in {0, 1}:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"grep_file 执行 ripgrep 失败：{stderr}")

    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return f"未找到匹配项: {regex}"
    if output_mode == "content":
        return _render_ripgrep_content(stdout_lines, regex=regex, limit=limit)
    if output_mode == "files_with_matches":
        return _render_ripgrep_files(stdout_lines, regex=regex, limit=limit, search_path=search_path)
    return _render_ripgrep_counts(stdout_lines, regex=regex, search_path=search_path)


def _render_ripgrep_content(lines: list[str], *, regex: str, limit: int) -> str:
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
        entries.append((_normalize_ripgrep_relative_path(file_path), parsed_line_number, content))
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
        rendered.append(f"# Note: output truncated at {limit} matches, narrow regex/glob/search_path.")
    return "\n".join(rendered)


def _render_ripgrep_files(lines: list[str], *, regex: str, limit: int, search_path: str) -> str:
    normalized_files = sorted(_normalize_ripgrep_relative_path(line) for line in lines if line.strip())
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
        rendered.append("# Note: file results truncated, narrow regex/glob/search_path.")
    return "\n".join(rendered)


def _render_ripgrep_counts(lines: list[str], *, regex: str, search_path: str) -> str:
    rendered = [f"# Search path: {search_path}", f"# Regex: {regex}"]
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
        rows.append((_normalize_ripgrep_relative_path(file_path), count))
    rendered.insert(2, f"# Total matches: {total_matches}")
    for file_path, count in sorted(rows, key=lambda item: item[0]):
        rendered.append(f"{file_path}: {count}")
    return "\n".join(rendered)


def _run_python_grep(
    *,
    regex: str,
    target: Path,
    workspace: Path,
    output_mode: str,
    glob_pattern: str,
    file_type: str,
    respect_ignored: bool,
    limit: int,
) -> str:
    pattern = re.compile(regex, re.MULTILINE)
    candidate_files = [target] if target.is_file() else _collect_search_files(target, respect_ignored)
    filtered_files = [
        file_path
        for file_path in candidate_files
        if _matches_glob(file_path, target if target.is_dir() else target.parent, glob_pattern)
        and _matches_file_type(file_path, file_type)
    ]

    if output_mode == "files_with_matches":
        rendered_files: list[str] = []
        for file_path in filtered_files:
            if _find_matching_line_numbers(pattern, _safe_split_lines(file_path)):
                rendered_files.append(_relative_posix_path(file_path, workspace))
            if len(rendered_files) >= limit:
                break
        if not rendered_files:
            return f"未找到匹配项: {regex}"
        rendered = [
            f"# Search path: {_relative_posix_path(target, workspace) if target != workspace else '.'}",
            f"# Regex: {regex}",
            f"# Returned files: {len(rendered_files)}",
            f"# Limit: {limit}",
            f"# Truncated: {'true' if len(rendered_files) == limit else 'false'}",
            *rendered_files,
        ]
        if len(rendered_files) == limit:
            rendered.append("# Note: file results truncated, narrow regex/glob/search_path.")
        return "\n".join(rendered)

    if output_mode == "count":
        rendered = [f"# Regex: {regex}"]
        total_matches = 0
        for file_path in filtered_files:
            match_line_numbers = _find_matching_line_numbers(pattern, _safe_split_lines(file_path))
            if not match_line_numbers:
                continue
            total_matches += len(match_line_numbers)
            rendered.append(f"{_relative_posix_path(file_path, workspace)}: {len(match_line_numbers)}")
        if total_matches == 0:
            return f"未找到匹配项: {regex}"
        rendered.insert(1, f"# Total matches: {total_matches}")
        return "\n".join(rendered)

    rendered: list[str] = []
    matched_lines = 0
    for file_path in filtered_files:
        lines = _safe_split_lines(file_path)
        match_line_numbers = _find_matching_line_numbers(pattern, lines)
        if not match_line_numbers:
            continue
        rendered.append(f"# File: {_relative_posix_path(file_path, workspace)}")
        for line_number in match_line_numbers:
            rendered.append(f"{line_number} | {lines[line_number - 1]}")
            matched_lines += 1
            if matched_lines >= limit:
                rendered.append(f"# Note: output truncated at {limit} matches, narrow regex/glob/search_path.")
                return "\n".join(rendered)
    return "\n".join(rendered) if rendered else f"未找到匹配项: {regex}"


def _collect_search_files(target: Path, respect_ignored: bool) -> list[Path]:
    candidate_files: list[Path] = []
    _append_search_files(target, candidate_files, respect_ignored)
    return candidate_files


def _append_search_files(current: Path, candidate_files: list[Path], respect_ignored: bool) -> None:
    for child in sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if respect_ignored and child.is_dir() and child.name in DEFAULT_IGNORED_DIR_NAMES:
            continue
        if child.is_dir():
            _append_search_files(child, candidate_files, respect_ignored)
            continue
        candidate_files.append(child)


def _find_matching_line_numbers(pattern: re.Pattern[str], lines: list[str]) -> list[int]:
    return [line_number for line_number, line in enumerate(lines, start=1) if pattern.search(line)]


def _safe_split_lines(file_path: Path) -> list[str]:
    try:
        return file_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []


def _matches_glob(file_path: Path, search_root: Path, glob_pattern: str) -> bool:
    if not glob_pattern:
        return True
    relative_path = _relative_posix_path(file_path, search_root)
    return fnmatch.fnmatch(relative_path, glob_pattern) or fnmatch.fnmatch(file_path.name, glob_pattern)


def _matches_file_type(file_path: Path, file_type: str) -> bool:
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


def _normalize_ripgrep_relative_path(file_path: str) -> str:
    normalized = file_path.replace("\\", "/").strip()
    return normalized[2:] if normalized.startswith("./") else normalized


def write_file(ctx: ToolContext, filename: str, content: str) -> str:
    """创建并写入新文件，若文件已存在会报错。"""

    files = WorkspaceFiles.from_context(ctx)
    target = files.resolve_path(filename)
    if target.exists():
        raise FileExistsError(f"文件已存在，禁止覆写: {filename}")
    target.parent.mkdir(parents=True, exist_ok=True)
    files.write_text(target, content)
    return f"已创建文件: {filename}"


def apply_patch(
    ctx: ToolContext,
    filename: str,
    edits: list[dict[str, Any]] | str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    new_content: str = "",
) -> dict[str, object]:
    """基于起止行号替换文件内容；同一文件的多处修改应合并到一次 edits 调用。"""

    normalized_edits = _parse_edits(edits, start_line=start_line, end_line=end_line, new_content=new_content)
    files = WorkspaceFiles.from_context(ctx)
    target = files.resolve_path(filename)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not target.is_file():
        raise IsADirectoryError(f"目标不是文件: {filename}")

    original_text = files.read_text(target)
    had_trailing_newline = original_text.endswith("\n")
    lines = original_text.splitlines()
    total_lines = len(lines)
    normalized = [
        _normalize_edit(edit, total_lines, index)
        for index, edit in enumerate(normalized_edits, start=1)
    ]
    previous_end_line = -1
    for current_start_line, current_end_line, _current_new_content in sorted(normalized, key=lambda edit: (edit[0], edit[1])):
        if current_start_line <= previous_end_line:
            raise ValueError("edits 不能包含重叠的行号区间")
        previous_end_line = max(previous_end_line, current_end_line)

    updated_lines = lines[:]
    for current_start_line, current_end_line, current_new_content in sorted(normalized, key=lambda edit: (edit[0], edit[1]), reverse=True):
        updated_lines[current_start_line - 1 : current_end_line] = current_new_content.splitlines()
    updated_text = "\n".join(updated_lines)
    if had_trailing_newline and (updated_text or original_text):
        updated_text += "\n"
    files.write_text(target, updated_text)
    return {"summary": f"已修改文件 {filename} 的 {len(normalized)} 处行号区间。", "files": [filename]}


def _parse_edits(
    edits: list[dict[str, Any]] | str | None,
    *,
    start_line: int | None,
    end_line: int | None,
    new_content: str,
) -> list[dict[str, Any]]:
    if edits:
        if isinstance(edits, str):
            try:
                parsed = json.loads(edits)
            except json.JSONDecodeError as exc:
                raise ValueError("edits 字符串必须是 JSON 数组") from exc
            edits = parsed
        if not isinstance(edits, list):
            raise ValueError("edits 必须是非空数组")
        return edits
    if start_line is None or end_line is None:
        raise ValueError("apply_patch 需要 edits，或旧参数 start_line、end_line、new_content")
    return [{"start_line": start_line, "end_line": end_line, "new_content": new_content}]


def _normalize_edit(edit: dict[str, Any], total_lines: int, index: int) -> tuple[int, int, str]:
    try:
        start_line = int(edit["start_line"])
        end_line = int(edit["end_line"])
    except KeyError as exc:
        raise ValueError(f"edits[{index}] 缺少 {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"edits[{index}] 的 start_line 和 end_line 必须是整数") from exc

    if "new_content" not in edit:
        raise ValueError(f"edits[{index}] 缺少 new_content")
    new_content = str(edit.get("new_content", ""))
    if start_line < 1 or end_line < 0:
        raise ValueError("start_line 必须 >= 1，end_line 必须 >= 0")
    if start_line > end_line + 1:
        raise ValueError("start_line 不能大于 end_line + 1")
    if start_line > total_lines + 1:
        raise ValueError(f"start_line ({start_line}) 超出文件总行数 ({total_lines})")
    if end_line > total_lines:
        raise ValueError(f"end_line ({end_line}) 超出文件总行数 ({total_lines})")
    return start_line, end_line, new_content


def replace_file(ctx: ToolContext, filename: str, old_content: str, new_content: str) -> str:
    """替换已有文件中的一段内容，old_content 必须唯一匹配。"""

    files = WorkspaceFiles.from_context(ctx)
    target = files.resolve_path(filename)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not target.is_file():
        raise IsADirectoryError(f"目标不是文件: {filename}")

    content = files.read_text(target)
    occurrences = content.count(old_content)
    if occurrences == 0:
        raise ValueError("未找到要替换的 old_content。")
    if occurrences > 1:
        raise ValueError("old_content 匹配到多处内容，请提供更精确的上下文。")
    files.write_text(target, content.replace(old_content, new_content, 1))
    return f"已更新文件: {filename}"


def delete_file(ctx: ToolContext, filename: str) -> dict[str, object]:
    """请求删除文件的用户确认。"""

    files = WorkspaceFiles.from_context(ctx)
    target = files.resolve_path(filename)
    if not target.exists():
        raise FileNotFoundError(f"文件不存在: {filename}")
    if not target.is_file():
        raise IsADirectoryError(f"目标不是文件: {filename}")
    ctx.state.request_stop("")
    return {
        "requires_confirmation": True,
        "filename": filename,
        "absolute_path": str(target),
        "message": f"确认删除文件 {filename}？",
    }


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


list_file.supports_parallel = True
glob_file.supports_parallel = True
read_file.supports_parallel = True
grep_file.supports_parallel = True
