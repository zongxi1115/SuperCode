from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from zonix.tools import ToolContext


def _hidden_windows_process_kwargs() -> dict[str, object]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _parse_bool_argument(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _ensure_git_workspace(workspace: Path) -> Path:
    workspace_root = workspace.resolve()
    if not (workspace_root / ".git").exists():
        raise RuntimeError("当前工作区不是 git 仓库。")
    return workspace_root


def git_commit(ctx: ToolContext, message: str) -> dict[str, object]:
    """暂存所有变更并创建 git 提交，执行前需要用户确认。"""

    message = message.strip()
    if not message:
        raise ValueError("提交信息不能为空。")

    workspace = _ensure_git_workspace(Path(ctx.workspace))
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        **_hidden_windows_process_kwargs(),
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
    ctx.state.request_stop("")
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
        **_hidden_windows_process_kwargs(),
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
        **_hidden_windows_process_kwargs(),
    )
    if commit_result.returncode != 0:
        stderr = commit_result.stderr.strip()
        if "nothing to commit" in stderr or "nothing to commit" in commit_result.stdout:
            return "没有待提交的变更。"
        raise RuntimeError(f"git commit 失败：{stderr}")

    return commit_result.stdout.strip() or "提交成功。"


def git_log(ctx: ToolContext, count: int = 20) -> str:
    """查看 git 提交历史。"""

    count = min(max(int(count), 1), 100)
    workspace = _ensure_git_workspace(Path(ctx.workspace))
    result = subprocess.run(
        ["git", "log", f"-{count}", "--pretty=format:%h|%an|%ai|%s"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        **_hidden_windows_process_kwargs(),
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


def git_tag(
    ctx: ToolContext,
    tag: str = "",
    message: str = "",
    list: bool = False,  # noqa: A002
) -> dict[str, object]:
    """管理 git 标签；创建标签前需要用户确认。"""

    list_tags = _parse_bool_argument(list)
    workspace = _ensure_git_workspace(Path(ctx.workspace))
    if list_tags:
        result = subprocess.run(
            ["git", "tag", "-l", "--sort=-creatordate"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **_hidden_windows_process_kwargs(),
        )
        tags = [item.strip() for item in result.stdout.strip().splitlines() if item.strip()]
        return {"tags": tags, "count": len(tags)}

    tag_name = tag.strip()
    if not tag_name:
        raise ValueError("创建标签必须提供 tag 名称。")

    tag_message = message.strip() or f"Release {tag_name}"
    ctx.state.request_stop("")
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
        **_hidden_windows_process_kwargs(),
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
        **_hidden_windows_process_kwargs(),
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

    subprocess.run(
        ["git", "add", "-A"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        **_hidden_windows_process_kwargs(),
    )

    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        **_hidden_windows_process_kwargs(),
    )

    return "已初始化 git 仓库并创建 .gitignore。"


git_log.supports_parallel = True
