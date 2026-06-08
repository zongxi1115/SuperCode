from __future__ import annotations

from contextlib import asynccontextmanager

import signal

import asyncio
import json
import os
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent import AgentEvent
from coding_agent import InteractiveCommandSession
from fastapi_app.app_config import (
    APP_DATA_ROOT,
    DEFAULT_BROWSER_PREVIEW_URL,
    STATE_DB_PATH,
    hidden_windows_process_kwargs,
    is_desktop_mode,
    normalize_reasoning_effort,
)
from fastapi_app.api_models import (
    CreateSessionResponse,
    EmbeddingSettingsPayload,
    SettingsPayload,
    UIModelProviderPayload,
)
from fastapi_app.runtime.chat import ChatRuntimeDeps, register_chat_routes
from fastapi_app.code_changes import extract_apply_patch_paths
from fastapi_app.routes.config import ConfigRouteDeps, register_config_routes
from fastapi_app.runtime.context import (
    ContextRuntimeDeps,
    auto_compress_session_context_if_needed,
    build_session_state_payload,
    compact_text,
    compress_session_context,
    invalidate_session_context_usage,
    merge_session_token_usage,
)
from fastapi_app.routes.file import FileRouteDeps, register_file_routes
from fastapi_app.routes.git import GitRouteDeps, register_git_routes
from fastapi_app.kanban_store import KanbanStore
from fastapi_app.routes.plugin import PluginRouteDeps, register_plugin_routes
from fastapi_app.routes.misc import MiscRouteDeps, register_misc_routes
from fastapi_app.routes.mcp import MCPRouteDeps, register_mcp_routes
from fastapi_app.session_history import (
    append_assistant_part_delta,
    append_assistant_tool_call,
    clear_assistant_text_part,
    ensure_user_message_recorded,
    extract_message_thought_text,
    extract_preview_url,
    extract_terminal_output,
    finalize_plan_steps,
    replace_assistant_text_part,
    sync_assistant_message_fields,
    update_assistant_history_message,
    update_plan_steps_for_tool,
    upsert_assistant_thinking_part,
    upsert_message,
)
from fastapi_app.routes.session import SessionRouteDeps, register_session_routes
from fastapi_app.routes.session_ops import SessionOpsRouteDeps, register_session_ops_routes
from fastapi_app.routes.plan import register_plan_routes
from fastapi_app.runtime.session import build_task_status_payload, create_task_in_session, finish_task_step_in_session
from fastapi_app.routes.terminal import TerminalRouteDeps, register_terminal_routes
from fastapi_app.runtime.terminal import TerminalRuntimeBase
from fastapi_app.routes.tool_interaction import ToolInteractionRouteDeps, register_tool_interaction_routes
from fastapi_app.ui_message_stream import UIMessageStreamAdapter, sse_data
from fastapi_app.routes.workspace import WorkspaceRouteDeps, register_workspace_routes
from fastapi_app.runtime.worktree import (
    WorktreeRuntimeDeps,
    create_session_worktree,
    fork_session_from_current,
    move_session_to_worktree,
    normalize_execution_mode as normalize_execution_mode_impl,
    restore_session_to_message,
    session_has_pending_context_interaction,
)
from fastapi_app.session.agent_runtime import (
    attach_agent_runtime_metadata,
    build_chat_session,
    extract_command_exit_code,
    get_loaded_plugin_ids,
    normalize_deploy_state,
    normalize_plan_state,
    rebuild_chat_session_for_agent_type,
    refresh_session_runtime_state,
    reset_phase_for_new_turn,
    route_session_for_user_message,
    set_loaded_plugin_ids,
    set_session_phase,
    sync_session_runtime_state_for_agent,
    update_deploy_state,
    update_plan_state,
)
from fastapi_app.session.helpers import (
    list_workspace_options,
    normalize_agent_type,
    normalize_workspace,
    normalize_workspace_identifier,
    resolve_model_option,
    resolve_model_reference_id,
    resolve_requested_env_file,
)
from fastapi_app.session.lifecycle import SessionRegistry
from fastapi_app.session.ui_session import UISession, UISessionBindings
from fastapi_app.session_store import SQLiteSessionStateAdapter
from fastapi_app.skills import list_available_skill_summaries
from fastapi_app.workspace_utils import list_child_directories, resolve_workspace_path
_session_store = SQLiteSessionStateAdapter(STATE_DB_PATH)
_kanban_store = KanbanStore(STATE_DB_PATH)
SESSION_BINDINGS = UISessionBindings(
    sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
    persist_session_state=lambda session: SESSION_REGISTRY.persist_session_state(session),
    resolve_model_reference_id=resolve_model_reference_id,
    list_workspace_options=list_workspace_options,
)
SESSION_REGISTRY = SessionRegistry(
    session_store=_session_store,
    session_factory=lambda **kwargs: UISession(bindings=SESSION_BINDINGS, **kwargs),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _cleanup_sessions() -> None:
        for session in SESSION_REGISTRY.sessions.values():
            SESSION_REGISTRY.stop_session_execution(session)
            for runtime in session.terminal_runtimes.values():
                runtime.close()
            if session.interactive_command_session is not None:
                session.interactive_command_session.close()

    yield

    _cleanup_sessions()


app = FastAPI(
    title="SuperCode Agent UI API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def normalize_execution_mode(raw_mode: str | None) -> str:
    return normalize_execution_mode_impl(raw_mode)


def require_session(session_id: str) -> UISession:
    return SESSION_REGISTRY.require_session(session_id)


def persist_session_state(session: UISession) -> None:
    SESSION_REGISTRY.persist_session_state(session)


def stop_session_execution(session: UISession) -> list[dict[str, Any]]:
    return SESSION_REGISTRY.stop_session_execution(session)


def set_session_generating(session: UISession, is_generating: bool) -> None:
    SESSION_REGISTRY.set_session_generating(session, is_generating)


def persisted_state_to_history_item(state: Any) -> Any:
    return SESSION_REGISTRY.persisted_state_to_history_item(state)


register_plan_routes(
    app,
    require_session=require_session,
    rebuild_chat_session_for_agent_type=rebuild_chat_session_for_agent_type,
    invalidate_session_context_usage=invalidate_session_context_usage,
)

register_misc_routes(
    app,
    deps=MiscRouteDeps(
        normalize_workspace=normalize_workspace,
        list_child_directories=list_child_directories,
    ),
)

register_file_routes(
    app,
    deps=FileRouteDeps(
        require_session=require_session,
    ),
)

register_git_routes(
    app,
    deps=GitRouteDeps(
        require_session=require_session,
        hidden_windows_process_kwargs=hidden_windows_process_kwargs,
    ),
)

register_plugin_routes(
    app,
    deps=PluginRouteDeps(
        require_session=require_session,
        get_loaded_plugin_ids=get_loaded_plugin_ids,
        set_loaded_plugin_ids=set_loaded_plugin_ids,
        rebuild_chat_session_for_agent_type=rebuild_chat_session_for_agent_type,
    ),
)

register_workspace_routes(
    app,
    deps=WorkspaceRouteDeps(
        kanban_store=_kanban_store,
        list_workspace_options=list_workspace_options,
        normalize_workspace_identifier=normalize_workspace_identifier,
    ),
)

register_config_routes(
    app,
    deps=ConfigRouteDeps(
        app_data_root=APP_DATA_ROOT,
        require_session=require_session,
        resolve_model_option=resolve_model_option,
        resolve_model_reference_id=resolve_model_reference_id,
        normalize_reasoning_effort=normalize_reasoning_effort,
        attach_agent_runtime_metadata=attach_agent_runtime_metadata,
        sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
        invalidate_session_context_usage=invalidate_session_context_usage,
        get_loaded_plugin_ids=get_loaded_plugin_ids,
    ),
)

register_mcp_routes(
    app,
    deps=MCPRouteDeps(
        app_data_root=APP_DATA_ROOT,
    ),
)

register_tool_interaction_routes(
    app,
    deps=ToolInteractionRouteDeps(
        require_session=require_session,
        set_session_phase=set_session_phase,
        update_deploy_state=update_deploy_state,
        update_plan_state=update_plan_state,
    ),
)

register_terminal_routes(
    app,
    deps=TerminalRouteDeps(
        require_session=require_session,
        is_desktop_mode=is_desktop_mode,
    ),
)

CONTEXT_RUNTIME_DEPS = ContextRuntimeDeps(
    app_data_root=APP_DATA_ROOT,
    normalize_reasoning_effort=normalize_reasoning_effort,
    resolve_model_option=resolve_model_option,
    sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
)

WORKTREE_RUNTIME_DEPS = WorktreeRuntimeDeps(
    hidden_windows_process_kwargs=hidden_windows_process_kwargs,
    build_chat_session=build_chat_session,
    rebuild_chat_session_for_agent_type=rebuild_chat_session_for_agent_type,
    attach_agent_runtime_metadata=attach_agent_runtime_metadata,
    refresh_session_runtime_state=refresh_session_runtime_state,
    sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
    persist_session_state=persist_session_state,
    stop_session_execution=stop_session_execution,
    set_session_phase=set_session_phase,
    invalidate_session_context_usage=invalidate_session_context_usage,
    interactive_command_session_factory=lambda workspace: InteractiveCommandSession(
        workspace=resolve_workspace_path(workspace)
    ),
    default_browser_preview_url=DEFAULT_BROWSER_PREVIEW_URL,
    session_factory=SESSION_REGISTRY.session_factory,
    register_session=SESSION_REGISTRY.register,
)

register_session_routes(
    app,
    deps=SessionRouteDeps(
        session_factory=SESSION_REGISTRY.session_factory,
        sessions_dict=SESSION_REGISTRY.sessions,
        session_store=_session_store,
        require_session=require_session,
        normalize_workspace=normalize_workspace,
        normalize_execution_mode=normalize_execution_mode,
        normalize_agent_type=normalize_agent_type,
        normalize_reasoning_effort=normalize_reasoning_effort,
        resolve_requested_env_file=resolve_requested_env_file,
        build_chat_session=build_chat_session,
        resolve_workspace_path=resolve_workspace_path,
        interactive_command_session_factory=lambda workspace: InteractiveCommandSession(
            workspace=resolve_workspace_path(workspace)
        ),
        attach_agent_runtime_metadata=attach_agent_runtime_metadata,
        sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
        persist_session_state=persist_session_state,
        stop_session_execution=stop_session_execution,
        persisted_state_to_history_item=persisted_state_to_history_item,
        list_workspace_options=list_workspace_options,
        list_available_skill_summaries=list_available_skill_summaries,
        create_session_response_factory=CreateSessionResponse,
        create_session_worktree=create_session_worktree,
        worktree_runtime_deps=WORKTREE_RUNTIME_DEPS,
    ),
)

register_session_ops_routes(
    app,
    deps=SessionOpsRouteDeps(
        require_session=require_session,
        create_task_in_session=create_task_in_session,
        finish_task_step_in_session=finish_task_step_in_session,
        build_task_status_payload=build_task_status_payload,
        session_has_pending_context_interaction=session_has_pending_context_interaction,
        compress_session_context=compress_session_context,
        context_runtime_deps=CONTEXT_RUNTIME_DEPS,
        fork_session_from_current=fork_session_from_current,
        restore_session_to_message=restore_session_to_message,
        worktree_runtime_deps=WORKTREE_RUNTIME_DEPS,
    ),
)

register_chat_routes(
    app,
    deps=ChatRuntimeDeps(
        app_data_root=APP_DATA_ROOT,
        require_session=require_session,
        normalize_execution_mode=normalize_execution_mode,
        move_session_to_worktree=lambda session: move_session_to_worktree(
            session,
            deps=WORKTREE_RUNTIME_DEPS,
        ),
        normalize_agent_type=normalize_agent_type,
        route_session_for_user_message=route_session_for_user_message,
        update_plan_state=update_plan_state,
        stop_session_execution=stop_session_execution,
        reset_phase_for_new_turn=reset_phase_for_new_turn,
        sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
        set_session_generating=set_session_generating,
        build_session_state_payload=build_session_state_payload,
        merge_session_token_usage=merge_session_token_usage,
        set_session_phase=set_session_phase,
        update_deploy_state=update_deploy_state,
        compact_text=compact_text,
        extract_command_exit_code=extract_command_exit_code,
        context_runtime_deps=CONTEXT_RUNTIME_DEPS,
        auto_compress_session_context_if_needed=auto_compress_session_context_if_needed,
    ),
)


if __name__ == "__main__":
    import uvicorn

    def _force_shutdown(signum: int, frame: Any) -> None:
        for session in SESSION_REGISTRY.sessions.values():
            stop_session_execution(session)
            for runtime in session.terminal_runtimes.values():
                runtime.close()
            if session.interactive_command_session is not None:
                session.interactive_command_session.close()
        import os
        os._exit(0)

    signal.signal(signal.SIGINT, _force_shutdown)
    signal.signal(signal.SIGTERM, _force_shutdown)

    uvicorn.run(app, host="0.0.0.0", port=3001)

