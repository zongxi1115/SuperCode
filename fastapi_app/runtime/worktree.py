from __future__ import annotations

import subprocess
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from deploy_agent import DeployConnectionManager
from fastapi_app.session_history import extract_message_thought_text, seed_chat_session_history
from fastapi_app.workspace_utils import resolve_workspace_path


@dataclass(frozen=True)
class WorktreeSessionLocation:
    workspace: str
    execution_mode: str
    base_workspace: str
    worktree_path: str
    worktree_branch: str


@dataclass(frozen=True)
class WorktreeRuntimeDeps:
    session_registry: Any
    hidden_windows_process_kwargs: Callable[[], dict[str, Any]]
    build_chat_session: Callable[..., tuple[Any, str, str | None, str | None, str | None, int | None]]
    rebuild_chat_session_for_agent_type: Callable[[Any, str], None]
    attach_agent_runtime_metadata: Callable[..., None]
    refresh_session_runtime_state: Callable[[Any], None]
    sync_session_runtime_state_for_agent: Callable[[Any], None]
    set_session_phase: Callable[[Any, str], None]
    invalidate_session_context_usage: Callable[[Any], None]
    interactive_command_session_factory: Callable[[str], Any]
    default_browser_preview_url: str


def normalize_execution_mode(raw_mode: str | None) -> str:
    normalized = str(raw_mode or "local").strip().lower()
    if normalized not in {"local", "worktree"}:
        raise HTTPException(status_code=400, detail=f"不支持的运行模式: {raw_mode}")
    return normalized


def run_git_command(args: list[str], cwd: Path, *, deps: WorktreeRuntimeDeps) -> subprocess.CompletedProcess[str]:
    popen_kwargs = deps.hidden_windows_process_kwargs()
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="未找到 git 命令，无法创建 worktree") from exc


def ensure_git_worktree_source(source_workspace: str, *, deps: WorktreeRuntimeDeps) -> Path:
    source_path = resolve_workspace_path(source_workspace)
    if not source_path.exists() or not source_path.is_dir():
        raise HTTPException(status_code=400, detail="工作区必须是已存在的目录")
    result = run_git_command(["rev-parse", "--is-inside-work-tree"], source_path, deps=deps)
    if result.returncode != 0 or result.stdout.strip().lower() != "true":
        raise HTTPException(status_code=400, detail="工作树模式需要选择一个已有 git 仓库")
    return source_path


def create_session_worktree(
    *,
    session_id: str,
    source_workspace: str,
    deps: WorktreeRuntimeDeps,
    base_workspace: str | None = None,
) -> WorktreeSessionLocation:
    source_path = ensure_git_worktree_source(source_workspace, deps=deps)
    base_path = resolve_workspace_path(base_workspace or source_workspace)
    short_id = session_id[:8]
    branch_name = f"supercode/session-{short_id}"
    worktrees_root = base_path.parent / f"{base_path.name}.worktrees"
    worktree_path = worktrees_root / f"sc-{short_id}"
    if worktree_path.exists():
        raise HTTPException(status_code=409, detail=f"worktree 目录已存在：{worktree_path}")
    worktrees_root.mkdir(parents=True, exist_ok=True)
    result = run_git_command(
        ["worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"],
        source_path,
        deps=deps,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "创建 git worktree 失败").strip()
        raise HTTPException(status_code=400, detail=detail)
    resolved_worktree = str(worktree_path.resolve())
    return WorktreeSessionLocation(
        workspace=resolved_worktree,
        execution_mode="worktree",
        base_workspace=str(base_path.resolve()),
        worktree_path=resolved_worktree,
        worktree_branch=branch_name,
    )


def remap_path_between_workspaces(raw_path: str | None, old_workspace: str, new_workspace: str) -> str | None:
    if raw_path is None or not str(raw_path).strip():
        return raw_path
    candidate = Path(str(raw_path)).expanduser()
    if not candidate.is_absolute():
        return raw_path
    try:
        relative = candidate.resolve().relative_to(resolve_workspace_path(old_workspace))
    except ValueError:
        return raw_path
    return str((resolve_workspace_path(new_workspace) / relative).resolve())


def remap_open_files_between_workspaces(
    open_files: list[str],
    old_workspace: str,
    new_workspace: str,
) -> list[str]:
    return [
        remap_path_between_workspaces(path, old_workspace, new_workspace) or path
        for path in open_files
    ]


def session_has_pending_context_interaction(session: Any) -> bool:
    return any(
        (
            session.pending_user_input_requests,
            session.pending_connect_requests,
            session.pending_delete_confirmations,
            session.pending_commit_confirmations,
            session.pending_tag_confirmations,
        )
    )


def clone_deploy_connection_manager(
    session: Any,
    workspace: str | None = None,
) -> DeployConnectionManager:
    manager = DeployConnectionManager(workspace=resolve_workspace_path(workspace or session.workspace))
    for connection in session.deploy_connection_manager.export_state().values():
        if isinstance(connection, dict):
            manager.register_connection(deepcopy(connection))
    return manager


def move_session_to_worktree(session: Any, *, deps: WorktreeRuntimeDeps) -> None:
    if session.execution_mode == "worktree":
        return

    old_workspace = session.workspace
    location = create_session_worktree(
        session_id=session.session_id,
        source_workspace=session.workspace,
        base_workspace=session.base_workspace or session.workspace,
        deps=deps,
    )
    deploy_connection_manager = clone_deploy_connection_manager(session, location.workspace)

    deps.session_registry.stop_session_execution(session)
    for runtime in session.terminal_runtimes.values():
        runtime.close()
    if session.interactive_command_session is not None:
        session.interactive_command_session.close()

    session.workspace = location.workspace
    session.execution_mode = location.execution_mode
    session.base_workspace = location.base_workspace
    session.worktree_path = location.worktree_path
    session.worktree_branch = location.worktree_branch
    session.selected_file_path = remap_path_between_workspaces(
        session.selected_file_path,
        old_workspace,
        location.workspace,
    )
    session.open_files = remap_open_files_between_workspaces(
        session.open_files,
        old_workspace,
        location.workspace,
    )
    session.deploy_connection_manager = deploy_connection_manager
    session.interactive_command_session = deps.interactive_command_session_factory(location.workspace)
    session.terminal_runtimes.clear()
    session.default_terminal_id = None
    session.file_tree_loaded = False
    session.file_tree_dirty = True
    session.cached_file_tree = []
    session._ensure_default_terminal(location.workspace)

    deps.rebuild_chat_session_for_agent_type(session, session.agent_type)
    deps.sync_session_runtime_state_for_agent(session)
    session.touch()


def rebuild_chat_session_for_existing_history(
    *,
    session_id: str,
    workspace: str,
    execution_mode: str,
    base_workspace: str | None,
    worktree_path: str | None,
    worktree_branch: str | None,
    env_file: str | None,
    agent_type: str,
    reasoning_effort: str | None,
    history_messages: list[dict[str, Any]],
    history_tools: list[dict[str, Any]],
    deploy_connection_manager: DeployConnectionManager,
    phase: str,
    selected_file_path: str | None,
    open_files: list[str],
    terminal_output: str,
    preview_url: str,
    code_changes: list[dict[str, Any]],
    thoughts: list[str],
    plan_steps: list[dict[str, str]],
    plan_state: dict[str, Any],
    route_state: dict[str, Any],
    deploy_state: dict[str, Any],
    startup_error: str | None,
    mode: str,
    deps: WorktreeRuntimeDeps,
) -> Any:
    (
        chat_session,
        model_name,
        build_error,
        env_file_used,
        resolved_reasoning_effort,
        context_limit,
    ) = deps.build_chat_session(
        workspace,
        env_file,
        agent_type=agent_type,
        reasoning_effort=reasoning_effort,
        loaded_plugin_ids={
            str(plugin_id).strip()
            for plugin_id in route_state.get("loadedPlugins", [])
            if str(plugin_id).strip()
        }
        if isinstance(route_state.get("loadedPlugins"), list)
        else set(),
    )
    interactive_command_session = deps.interactive_command_session_factory(workspace)
    session = deps.session_registry.session_factory(
        session_id=session_id,
        model=model_name if chat_session is not None else "Demo",
        reasoning_effort=resolved_reasoning_effort if chat_session is not None else reasoning_effort,
        workspace=workspace,
        execution_mode=execution_mode,
        base_workspace=base_workspace,
        worktree_path=worktree_path,
        worktree_branch=worktree_branch,
        mode="agent" if chat_session is not None else mode,
        agent_type=agent_type,
        phase=phase,
        route_state=deepcopy(route_state),
        is_generating=False,
        startup_error=startup_error if chat_session is not None else (build_error or startup_error),
        env_file=env_file_used or env_file,
        selected_file_path=selected_file_path,
        open_files=deepcopy(open_files),
        terminal_output=terminal_output,
        preview_url=preview_url or deps.default_browser_preview_url,
        interactive_command_session=interactive_command_session,
        chat_session=chat_session,
        history_messages=deepcopy(history_messages),
        history_tools=deepcopy(history_tools),
        code_changes=deepcopy(code_changes),
        thoughts=deepcopy(thoughts),
        plan_steps=deepcopy(plan_steps),
        plan_state=deepcopy(plan_state),
        deploy_connection_manager=deploy_connection_manager,
        deploy_state=deepcopy(deploy_state),
        max_context_tokens=context_limit,
    )
    session._ensure_default_terminal(workspace)
    if session.chat_session is not None:
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
    if session.chat_session is not None:
        deps.attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            deploy_connection_manager=deploy_connection_manager,
        )
        deps.sync_session_runtime_state_for_agent(session)
    return session


def fork_session_from_current(session: Any, *, deps: WorktreeRuntimeDeps) -> Any:
    new_session_id = uuid.uuid4().hex
    old_workspace = session.workspace
    location = create_session_worktree(
        session_id=new_session_id,
        source_workspace=session.workspace,
        base_workspace=session.base_workspace or session.workspace,
        deps=deps,
    )
    deploy_connection_manager = clone_deploy_connection_manager(session, location.workspace)
    forked_session = rebuild_chat_session_for_existing_history(
        session_id=new_session_id,
        workspace=location.workspace,
        execution_mode=location.execution_mode,
        base_workspace=location.base_workspace,
        worktree_path=location.worktree_path,
        worktree_branch=location.worktree_branch,
        env_file=session.env_file,
        agent_type=session.agent_type,
        reasoning_effort=session.reasoning_effort,
        history_messages=session.history_messages,
        history_tools=session.history_tools,
        deploy_connection_manager=deploy_connection_manager,
        phase=session.phase,
        selected_file_path=remap_path_between_workspaces(
            session.selected_file_path,
            old_workspace,
            location.workspace,
        ),
        open_files=remap_open_files_between_workspaces(
            session.open_files,
            old_workspace,
            location.workspace,
        ),
        terminal_output=session.terminal_output,
        preview_url=session.preview_url,
        code_changes=session.code_changes,
        thoughts=session.thoughts,
        plan_steps=session.plan_steps,
        plan_state=session.plan_state,
        route_state=session.route_state,
        deploy_state=session.deploy_state,
        startup_error=session.startup_error,
        mode=session.mode,
        deps=deps,
    )
    forked_session.created_at = int(time.time() * 1000)
    forked_session.updated_at = forked_session.created_at
    deps.refresh_session_runtime_state(forked_session)
    deps.sync_session_runtime_state_for_agent(forked_session)
    deps.session_registry.register(forked_session)
    deps.session_registry.persist_session_state(forked_session)
    return forked_session


def _collect_tool_call_ids_from_messages(messages: list[dict[str, Any]]) -> set[str]:
    tool_ids: set[str] = set()
    for message in messages:
        raw_tool_calls = message.get("toolCalls")
        if isinstance(raw_tool_calls, list):
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue
                tool_id = str(raw_tool_call.get("id") or "").strip()
                if tool_id:
                    tool_ids.add(tool_id)
        raw_parts = message.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if not isinstance(part, dict):
                continue
            raw_tool_call = part.get("toolCall")
            if not isinstance(raw_tool_call, dict):
                continue
            tool_id = str(raw_tool_call.get("id") or "").strip()
            if tool_id:
                tool_ids.add(tool_id)
    return tool_ids


def _collect_assistant_message_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {
        str(message.get("id") or "").strip()
        for message in messages
        if str(message.get("role", "")) == "assistant" and str(message.get("id") or "").strip()
    }


def _rebuild_thoughts_from_history_messages(messages: list[dict[str, Any]]) -> list[str]:
    thoughts: list[str] = []
    for message in messages:
        if str(message.get("role", "")) != "assistant":
            continue
        thought_text = extract_message_thought_text(message)
        if thought_text:
            thoughts.append(thought_text)
    return thoughts


def _filter_code_changes_for_restored_history(
    code_changes: list[dict[str, Any]],
    retained_assistant_ids: set[str],
    removed_assistant_ids: set[str],
    retained_tool_ids: set[str],
    removed_tool_ids: set[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for change in code_changes:
        assistant_id = str(change.get("assistantId") or "").strip()
        tool_call_id = str(change.get("ToolCallId") or change.get("toolCallId") or "").strip()
        if assistant_id and assistant_id in removed_assistant_ids:
            continue
        if tool_call_id and tool_call_id in removed_tool_ids:
            continue
        if assistant_id and retained_assistant_ids and assistant_id not in retained_assistant_ids and assistant_id in removed_assistant_ids:
            continue
        if tool_call_id and retained_tool_ids and tool_call_id not in retained_tool_ids and tool_call_id in removed_tool_ids:
            continue
        filtered.append(deepcopy(change))
    return filtered


def restore_session_to_message(session: Any, message_id: str, *, deps: WorktreeRuntimeDeps) -> Any:
    target_message_id = str(message_id or "").strip()
    if not target_message_id:
        raise HTTPException(status_code=400, detail="messageId 不能为空")

    target_index = next(
        (
            index
            for index, message in enumerate(session.history_messages)
            if str(message.get("id") or "").strip() == target_message_id
        ),
        -1,
    )
    if target_index < 0:
        raise HTTPException(status_code=404, detail="未找到对应的消息")

    target_message = session.history_messages[target_index]
    if str(target_message.get("role", "")) != "assistant":
        raise HTTPException(status_code=400, detail="只能还原到助手消息")

    kept_messages = deepcopy(session.history_messages[: target_index + 1])
    removed_messages = session.history_messages[target_index + 1 :]
    retained_tool_ids = _collect_tool_call_ids_from_messages(kept_messages)
    removed_tool_ids = _collect_tool_call_ids_from_messages(removed_messages)
    retained_assistant_ids = _collect_assistant_message_ids(kept_messages)
    removed_assistant_ids = _collect_assistant_message_ids(removed_messages)
    kept_tools = [
        deepcopy(tool)
        for tool in session.history_tools
        if str(tool.get("id") or "").strip() in retained_tool_ids
    ]
    kept_thoughts = _rebuild_thoughts_from_history_messages(kept_messages)
    kept_code_changes = _filter_code_changes_for_restored_history(
        session.code_changes,
        retained_assistant_ids=retained_assistant_ids,
        removed_assistant_ids=removed_assistant_ids,
        retained_tool_ids=retained_tool_ids,
        removed_tool_ids=removed_tool_ids,
    )

    session.history_messages = kept_messages
    session.history_tools = kept_tools
    session.thoughts = kept_thoughts
    deps.invalidate_session_context_usage(session)
    session.code_changes = kept_code_changes
    session.pending_user_input_requests.clear()
    session.pending_connect_requests.clear()
    session.pending_delete_confirmations.clear()
    session.pending_commit_confirmations.clear()
    session.pending_tag_confirmations.clear()
    deps.set_session_phase(session, "idle")
    if session.chat_session is not None:
        session.chat_session.clear()
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        deps.sync_session_runtime_state_for_agent(session)
    session.touch()
    return session.snapshot()
