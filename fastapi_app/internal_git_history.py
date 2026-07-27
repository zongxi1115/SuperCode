from __future__ import annotations

import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from fastapi_app.app_config import STATE_DB_PATH, hidden_windows_process_kwargs
from fastapi_app.workspace_utils import resolve_workspace_path


MAX_CHECKPOINT_DIFF_LINES = 80

HISTORY_EXCLUDES = """
.git/
.supercode/
.next/
.nuxt/
.pytest_cache/
.ruff_cache/
.turbo/
.venv/
venv/
__pycache__/
node_modules/
dist/
build/
coverage/
"""

_repo_locks: dict[str, threading.RLock] = {}
_repo_locks_guard = threading.RLock()


@dataclass(frozen=True)
class WorkspaceCheckpoint:
    before_ref: str | None
    after_ref: str
    checkpoint_ref: str
    records: list[dict[str, Any]]


def _history_root() -> Path:
    return STATE_DB_PATH.parent / "history" / "workspaces"


def _workspace_key(workspace: str | Path) -> str:
    resolved = str(Path(workspace).expanduser().resolve())
    return sha256(resolved.encode("utf-8")).hexdigest()


def _repo_path(workspace: str | Path) -> Path:
    return _history_root() / f"{_workspace_key(workspace)}.git"


def _lock_for_repo(repo: Path) -> threading.RLock:
    key = str(repo)
    with _repo_locks_guard:
        lock = _repo_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _repo_locks[key] = lock
        return lock


def _run_git(
    args: list[str],
    *,
    repo: Path | None = None,
    workspace: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if repo is not None:
        command.extend(["--git-dir", str(repo)])
    if workspace is not None:
        command.extend(["--work-tree", str(workspace)])
    command.extend(args)

    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "SuperCode")
    env.setdefault("GIT_AUTHOR_EMAIL", "supercode@local")
    env.setdefault("GIT_COMMITTER_NAME", "SuperCode")
    env.setdefault("GIT_COMMITTER_EMAIL", "supercode@local")

    try:
        result = subprocess.run(
            command,
            cwd=str(workspace or repo.parent if repo is not None else Path.cwd()),
            text=True,
            capture_output=True,
            check=False,
            env=env,
            **hidden_windows_process_kwargs(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 git 命令，无法记录内部历史。") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git 命令执行失败").strip()
        raise RuntimeError(detail)
    return result


def _ensure_repo(repo: Path) -> None:
    if not repo.exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare", str(repo)], check=True)
    exclude_path = repo / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    marker = "# SuperCode internal history excludes"
    if marker not in existing:
        suffix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_path.write_text(f"{existing}{suffix}{marker}\n{HISTORY_EXCLUDES.strip()}\n", encoding="utf-8")


def _session_ref_prefix(session_id: str) -> str:
    safe_session_id = re.sub(r"[^A-Za-z0-9._-]+", "-", session_id.strip()) or "unknown"
    return f"refs/supercode/sessions/{safe_session_id}"


def _latest_ref(session_id: str) -> str:
    return f"{_session_ref_prefix(session_id)}/latest"


def _baseline_ref(session_id: str) -> str:
    return f"{_session_ref_prefix(session_id)}/baseline"


def _checkpoint_ref(session_id: str, label: str) -> str:
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-") or "checkpoint"
    return f"{_session_ref_prefix(session_id)}/checkpoints/{int(time.time() * 1000)}-{safe_label}-{uuid.uuid4().hex[:8]}"


def _resolve_ref(repo: Path, ref: str) -> str | None:
    result = _run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo=repo, check=False)
    if result.returncode != 0:
        return None
    resolved = result.stdout.strip()
    return resolved or None


def _commit_tree(repo: Path, workspace: Path, tree: str, parent: str | None, message: str) -> str:
    args = ["commit-tree", tree]
    if parent:
        args.extend(["-p", parent])
    args.extend(["-m", message])
    return _run_git(args, repo=repo, workspace=workspace).stdout.strip()


def _commit_tree_id(repo: Path, commit: str) -> str:
    return _run_git(["rev-parse", f"{commit}^{{tree}}"], repo=repo).stdout.strip()


def _parse_name_status(output: str) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        action = "modified"
        if status.startswith("A"):
            action = "added"
        elif status.startswith("D"):
            action = "deleted"
        changes.append((path, action))
    return changes


def _parse_numstat(output: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        path = parts[-1]
        try:
            added = int(parts[0]) if parts[0] != "-" else 0
            deleted = int(parts[1]) if parts[1] != "-" else 0
        except ValueError:
            added, deleted = 0, 0
        stats[path] = (added, deleted)
    return stats


def _diff_preview(repo: Path, workspace: Path, before: str, after: str, path: str) -> str:
    result = _run_git(
        ["diff", "--no-ext-diff", "--unified=3", before, after, "--", path],
        repo=repo,
        workspace=workspace,
        check=False,
    )
    lines = result.stdout.splitlines()
    preview = lines[:MAX_CHECKPOINT_DIFF_LINES]
    if len(lines) > MAX_CHECKPOINT_DIFF_LINES:
        preview.append(f"... truncated {len(lines) - MAX_CHECKPOINT_DIFF_LINES} diff lines")
    return "\n".join(preview)


def _records_from_diff(
    *,
    repo: Path,
    workspace: Path,
    before: str,
    after: str,
    checkpoint_ref: str,
    source: str,
    label: str,
    tool_call_id: str | None,
    assistant_id: str | None,
    turn_index: int | None,
    step_index: int | None,
    timestamp: int,
) -> list[dict[str, Any]]:
    name_status = _run_git(
        ["diff", "--name-status", "-M", before, after, "--"],
        repo=repo,
        workspace=workspace,
        check=False,
    ).stdout
    numstat = _run_git(
        ["diff", "--numstat", "-M", before, after, "--"],
        repo=repo,
        workspace=workspace,
        check=False,
    ).stdout
    stats = _parse_numstat(numstat)
    records: list[dict[str, Any]] = []
    for path, action in _parse_name_status(name_status):
        added, deleted = stats.get(path, (0, 0))
        action_label = {"added": "新增", "modified": "修改", "deleted": "删除"}.get(action, "变更")
        absolute_path = workspace / path
        records.append(
            {
                "id": uuid.uuid4().hex,
                "action": action,
                "path": path,
                "absolutePath": str(absolute_path.resolve()),
                "source": source,
                "toolCallId": tool_call_id,
                "assistantId": assistant_id,
                "turnIndex": turn_index,
                "stepIndex": step_index,
                "timestamp": timestamp,
                "linesAdded": added,
                "linesDeleted": deleted,
                "summary": f"{label or action_label} {path}",
                "diffPreview": _diff_preview(repo, workspace, before, after, path),
                "beforeRef": before,
                "afterRef": after,
                "checkpointRef": checkpoint_ref,
                "checkpointLabel": label,
            }
        )
    return records


def session_has_history_baseline(session: Any) -> bool:
    repo = _repo_path(session.workspace)
    if not repo.exists():
        return False
    return _resolve_ref(repo, _latest_ref(session.session_id)) is not None


def create_workspace_checkpoint(
    session: Any,
    *,
    source: str,
    label: str,
    tool_call_id: str | None = None,
    assistant_id: str | None = None,
    turn_index: int | None = None,
    step_index: int | None = None,
    baseline_only: bool = False,
) -> WorkspaceCheckpoint | None:
    workspace = resolve_workspace_path(session.workspace)
    repo = _repo_path(workspace)
    lock = _lock_for_repo(repo)
    with lock:
        _ensure_repo(repo)
        before = _resolve_ref(repo, _latest_ref(session.session_id))
        _run_git(["add", "-A", "--", "."], repo=repo, workspace=workspace)
        tree = _run_git(["write-tree"], repo=repo, workspace=workspace).stdout.strip()
        if before is not None and _commit_tree_id(repo, before) == tree:
            return None

        checkpoint_ref = _checkpoint_ref(session.session_id, label)
        commit = _commit_tree(repo, workspace, tree, before, f"SuperCode {label}".strip())
        _run_git(["update-ref", checkpoint_ref, commit], repo=repo)
        _run_git(["update-ref", _latest_ref(session.session_id), commit], repo=repo)
        if before is None:
            _run_git(["update-ref", _baseline_ref(session.session_id), commit], repo=repo)

        records: list[dict[str, Any]] = []
        if before is not None and not baseline_only:
            timestamp = int(time.time() * 1000)
            records = _records_from_diff(
                repo=repo,
                workspace=workspace,
                before=before,
                after=commit,
                checkpoint_ref=checkpoint_ref,
                source=source,
                label=label,
                tool_call_id=tool_call_id,
                assistant_id=assistant_id,
                turn_index=turn_index,
                step_index=step_index,
                timestamp=timestamp,
            )
        return WorkspaceCheckpoint(
            before_ref=before,
            after_ref=commit,
            checkpoint_ref=checkpoint_ref,
            records=records,
        )


def ensure_workspace_history_baseline(session: Any) -> None:
    if session_has_history_baseline(session):
        return
    create_workspace_checkpoint(
        session,
        source="baseline",
        label="baseline",
        baseline_only=True,
    )


def delete_workspace_session_history(workspace: str | Path, session_id: str) -> None:
    repo = _repo_path(workspace)
    if not repo.exists():
        return
    lock = _lock_for_repo(repo)
    with lock:
        prefix = _session_ref_prefix(session_id)
        result = _run_git(
            ["for-each-ref", "--format=%(refname)", prefix],
            repo=repo,
            check=False,
        )
        if result.returncode != 0:
            return
        for ref in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            _run_git(["update-ref", "-d", ref], repo=repo, check=False)
