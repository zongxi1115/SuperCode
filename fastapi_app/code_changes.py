from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from fastapi_app.internal_git_history import (
    create_workspace_checkpoint,
    ensure_workspace_history_baseline,
)
from fastapi_app.workspace_utils import (
    normalize_relative_path,
    resolve_workspace_path,
)

MAX_CODE_CHANGE_RECORDS = 300
MUTATING_TOOL_NAMES = {
    "write_file",
    "replace_file",
    "apply_patch",
    "delete_file",
    "generate_image",
    "write_project_docs",
    "run_command",
    "execute",
    "start_task",
    "task_input",
    "task_wait",
    "task_stop",
}


def relative_workspace_path(path: str | Path, workspace: str) -> str:
    workspace_root = resolve_workspace_path(workspace)
    target = Path(path).expanduser().resolve()
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(target)


def count_text_lines(text: str | None) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def is_mutating_tool(tool_name: str) -> bool:
    return tool_name in MUTATING_TOOL_NAMES


def extract_apply_patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("*** Update File: "):
            continue
        path = line.removeprefix("*** Update File: ").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def capture_code_change_before_snapshots(
    session: Any,
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
) -> dict[str, str]:
    if is_mutating_tool(tool_name):
        ensure_code_change_baseline(session)
    return {}


def ensure_code_change_baseline(session: Any) -> None:
    try:
        ensure_workspace_history_baseline(session)
    except Exception:
        # Change tracking should never block the user's actual file operation.
        return


def _append_checkpoint_records(session: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    session.code_changes = [*session.code_changes, *records][-MAX_CODE_CHANGE_RECORDS:]
    return records


def record_workspace_checkpoint(
    session: Any,
    *,
    source: str = "agent",
    label: str = "变更",
    tool_call_id: str | None = None,
    assistant_id: str | None = None,
    turn_index: int | None = None,
    step_index: int | None = None,
) -> list[dict[str, Any]]:
    try:
        checkpoint = create_workspace_checkpoint(
            session,
            source=source,
            label=label,
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=turn_index,
            step_index=step_index,
        )
    except Exception:
        return []
    if checkpoint is None:
        return []
    return _append_checkpoint_records(session, checkpoint.records)


def record_code_change(
    session: Any,
    *,
    action: str,
    path: str | Path,
    before_text: str = "",
    after_text: str = "",
    source: str = "agent",
    tool_call_id: str | None = None,
    assistant_id: str | None = None,
    turn_index: int | None = None,
    step_index: int | None = None,
    summary: str | None = None,
) -> dict[str, Any] | None:
    if action == "modified" and before_text == after_text:
        return None

    absolute_path = Path(path).expanduser().resolve()
    relative_path = relative_workspace_path(absolute_path, session.workspace)
    if summary is None:
        action_label = {"added": "新增", "modified": "修改", "deleted": "删除"}.get(action, "变更")
        summary = f"{action_label} {relative_path}"

    records = record_workspace_checkpoint(
        session,
        source=source,
        label=summary,
        tool_call_id=tool_call_id,
        assistant_id=assistant_id,
        turn_index=turn_index,
        step_index=step_index,
    )
    for record in records:
        if str(record.get("path") or "") == relative_path:
            return record
    return records[0] if records else None


def current_agent_turn_index(session: Any) -> int | None:
    state = getattr(session.chat_session, "state", None)
    if state is None:
        return None
    turn_index = getattr(state, "turn_index", 0)
    return turn_index if isinstance(turn_index, int) and turn_index > 0 else None


def code_change_records_from_tool_result(
    session: Any,
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
    output: Any,
    tool_call_id: str,
    assistant_id: str,
    step_index: int | None,
    before_snapshots: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not is_mutating_tool(tool_name):
        return []
    label = {
        "write_file": "AI 写入",
        "replace_file": "AI 替换",
        "apply_patch": "AI 补丁",
        "delete_file": "AI 删除",
        "generate_image": "AI 生成资源",
        "write_project_docs": "AI 更新文档",
        "run_command": "命令执行",
        "execute": "命令执行",
        "start_task": "任务执行",
        "task_input": "任务输入",
        "task_wait": "任务等待",
        "task_stop": "任务停止",
    }.get(tool_name, "AI 变更")
    return record_workspace_checkpoint(
        session,
        source="agent",
        label=label,
        tool_call_id=tool_call_id,
        assistant_id=assistant_id,
        turn_index=current_agent_turn_index(session),
        step_index=step_index,
    )


def file_tree_changed_paths_from_tool_result(
    session: Any,
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
    output: Any,
) -> list[Path]:
    raw_paths: list[str] = []
    if tool_name in {"write_file", "replace_file", "delete_file"}:
        filename = str(tool_arguments.get("filename") or "").strip()
        if filename:
            raw_paths.append(filename)
    elif tool_name == "generate_image" and isinstance(output, dict):
        filename = str(output.get("file") or tool_arguments.get("filename") or "").strip()
        if filename:
            raw_paths.append(filename)
    elif tool_name == "apply_patch":
        if isinstance(output, dict) and isinstance(output.get("files"), list):
            raw_paths.extend(str(path) for path in output["files"] if str(path).strip())
        else:
            filename = str(tool_arguments.get("filename") or "").strip()
            if filename:
                raw_paths.append(filename)

    resolved: list[Path] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        try:
            target = Path(normalize_relative_path(raw_path, session.workspace))
        except HTTPException:
            continue
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(target)
    return resolved
