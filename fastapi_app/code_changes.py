from __future__ import annotations

import difflib
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from fastapi_app.workspace_utils import (
    normalize_relative_path,
    read_text_file,
    resolve_workspace_path,
)

MAX_CODE_CHANGE_RECORDS = 300
MAX_CODE_CHANGE_DIFF_LINES = 80


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
    raw_targets: list[str] = []
    if tool_name in {"replace_file", "delete_file"}:
        filename = str(tool_arguments.get("filename") or "").strip()
        if filename:
            raw_targets.append(filename)
    elif tool_name == "apply_patch":
        filename = str(tool_arguments.get("filename") or "").strip()
        if filename:
            raw_targets.append(filename)

    snapshots: dict[str, str] = {}
    for raw_target in raw_targets:
        try:
            target = Path(normalize_relative_path(raw_target, session.workspace))
        except HTTPException:
            continue
        relative_path = relative_workspace_path(target, session.workspace)
        snapshots[relative_path] = read_text_file(str(target), session.workspace)
    return snapshots


def build_code_diff_preview(relative_path: str, before_text: str, after_text: str) -> tuple[str, str, int, int]:
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    full_diff = "\n".join(diff_lines)
    preview_lines = diff_lines[:MAX_CODE_CHANGE_DIFF_LINES]
    if len(diff_lines) > MAX_CODE_CHANGE_DIFF_LINES:
        preview_lines.append(f"... truncated {len(diff_lines) - MAX_CODE_CHANGE_DIFF_LINES} diff lines")
    return "\n".join(preview_lines), full_diff, added, deleted


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
    diff_preview, full_diff, added, deleted = build_code_diff_preview(relative_path, before_text, after_text)
    if action == "added":
        added = count_text_lines(after_text)
        deleted = 0
    elif action == "deleted":
        added = 0
        deleted = count_text_lines(before_text)

    if summary is None:
        action_label = {"added": "新增", "modified": "修改", "deleted": "删除"}.get(action, "变更")
        summary = f"{action_label} {relative_path}"

    record = {
        "id": uuid.uuid4().hex,
        "action": action,
        "path": relative_path,
        "absolutePath": str(absolute_path),
        "source": source,
        "toolCallId": tool_call_id,
        "assistantId": assistant_id,
        "turnIndex": turn_index,
        "stepIndex": step_index,
        "timestamp": int(time.time() * 1000),
        "linesAdded": added,
        "linesDeleted": deleted,
        "summary": summary,
        "diffPreview": diff_preview,
        "fullDiff": full_diff,
    }
    session.code_changes = [*session.code_changes, record][-MAX_CODE_CHANGE_RECORDS:]
    return record


def current_agent_turn_index(session: Any) -> int | None:
    state = getattr(session.chat_session, "state", None)
    data = getattr(state, "data", None)
    if not isinstance(data, dict):
        return None
    try:
        return int(data.get("turn_index"))
    except (TypeError, ValueError):
        return None


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
    before_snapshots = before_snapshots or {}
    if tool_name == "write_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        after_text = read_text_file(str(target), session.workspace)
        record = record_code_change(
            session,
            action="added",
            path=target,
            before_text="",
            after_text=after_text,
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    if tool_name == "replace_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        relative_path = relative_workspace_path(target, session.workspace)
        before_text = before_snapshots.get(relative_path, str(tool_arguments.get("old_content") or ""))
        after_text = read_text_file(str(target), session.workspace)
        record = record_code_change(
            session,
            action="modified",
            path=target,
            before_text=before_text,
            after_text=after_text,
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    if tool_name == "apply_patch" and isinstance(output, dict):
        files = output.get("files")
        if not isinstance(files, list) or not files:
            return []
        records: list[dict[str, Any]] = []
        for raw_file in files:
            target = Path(normalize_relative_path(str(raw_file), session.workspace))
            relative_path = relative_workspace_path(target, session.workspace)
            after_text = read_text_file(str(target), session.workspace)
            record = record_code_change(
                session,
                action="modified",
                path=target,
                before_text=before_snapshots.get(relative_path, ""),
                after_text=after_text,
                source="agent",
                tool_call_id=tool_call_id,
                assistant_id=assistant_id,
                turn_index=current_agent_turn_index(session),
                step_index=step_index,
                summary=f"应用补丁 {relative_path}",
            )
            if record is not None:
                records.append(record)
        return records

    if tool_name == "delete_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        relative_path = relative_workspace_path(target, session.workspace)
        record = record_code_change(
            session,
            action="deleted",
            path=target,
            before_text=before_snapshots.get(relative_path, ""),
            after_text="",
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    return []


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
