from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

INTERACTIVE_INPUT_PROMPT_IDLE_SECONDS = 0.2
INTERACTIVE_POLL_SECONDS = 0.05
INTERACTIVE_COMMAND_MAX_OUTPUT_CHARS = 300_000
INTERACTIVE_STREAM_READ_CHUNK_SIZE = 4096
INTERACTIVE_PROMPT_TAIL_CHARS = 4096
DEFAULT_IGNORED_DIR_NAMES = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".supercode",
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
SUBAGENT_SUMMARY_MAX_CHARS = 6000
IMAGE_GENERATION_OUTPUT_DIR = ".supercode/generated-images"
IMAGE_GENERATION_ALLOWED_QUALITIES = {
    "auto",
    "low",
    "medium",
    "high",
    "standard",
    "hd",
}
IMAGE_GENERATION_EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
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


def _hidden_windows_process_kwargs(
    *, new_process_group: bool = False
) -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if new_process_group:
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": creationflags,
        "startupinfo": startupinfo,
    }


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
            **_hidden_windows_process_kwargs(),
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
                    **_hidden_windows_process_kwargs(),
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
                **_hidden_windows_process_kwargs(),
            )
        except Exception:
            continue

