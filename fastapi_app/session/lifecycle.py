from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from coding_agent import InteractiveCommandSession
from deploy_agent import DeployConnectionManager

from fastapi_app.app_config import DEFAULT_BROWSER_PREVIEW_URL
from fastapi_app.session.agent_runtime import (
    attach_agent_runtime_metadata,
    build_chat_session,
    sync_session_runtime_state_for_agent,
)
from fastapi_app.session_persistence import (
    persisted_state_to_history_item as persisted_state_to_history_item_impl,
    persist_session_state as persist_session_state_impl,
    session_has_persistable_history as session_has_persistable_history_impl,
    set_session_generating as set_session_generating_impl,
)
from fastapi_app.session_store import PersistedSessionState
from fastapi_app.session_history import seed_chat_session_history
from fastapi_app.workspace_utils import resolve_workspace_path


@dataclass
class SessionRegistry:
    session_store: Any
    session_factory: Callable[..., Any]
    interactive_command_session_factory: Callable[[str], Any] = field(
        default=lambda workspace: InteractiveCommandSession(
            workspace=resolve_workspace_path(workspace)
        )
    )
    sessions: dict[str, Any] = field(default_factory=dict)

    def register(self, session: Any) -> None:
        self.sessions[session.session_id] = session

    def session_has_persistable_history(self, session: Any) -> bool:
        return session_has_persistable_history_impl(session)

    def persist_session_state(self, session: Any) -> None:
        persist_session_state_impl(session, self.session_store)

    def set_session_generating(self, session: Any, is_generating: bool) -> None:
        set_session_generating_impl(session, is_generating)

    def persisted_state_to_history_item(self, state: PersistedSessionState) -> Any:
        return persisted_state_to_history_item_impl(state)

    def hydrate_session_from_state(self, state: PersistedSessionState) -> Any:
        deploy_connection_manager = DeployConnectionManager(
            workspace=resolve_workspace_path(state.workspace)
        )
        for connection in state.deploy_connections.values():
            if isinstance(connection, dict):
                deploy_connection_manager.register_connection(connection)

        (
            chat_session,
            model_name,
            startup_error,
            env_file_used,
            resolved_reasoning_effort,
            context_limit,
        ) = build_chat_session(
            state.workspace,
            state.env_file,
            reasoning_effort=state.reasoning_effort,
            agent_type=state.agent_type,
            loaded_plugin_ids={
                str(plugin_id).strip()
                for plugin_id in state.route_state.get("loadedPlugins", [])
                if str(plugin_id).strip()
            }
            if isinstance(state.route_state.get("loadedPlugins"), list)
            else set(),
            fallback_context_tokens=state.max_context_tokens,
        )
        interactive_command_session = self.interactive_command_session_factory(state.workspace)
        session = self.session_factory(
            session_id=state.session_id,
            model=model_name if chat_session is not None else state.model,
            reasoning_effort=resolved_reasoning_effort if chat_session is not None else state.reasoning_effort,
            workspace=state.workspace,
            execution_mode=state.execution_mode,
            base_workspace=state.base_workspace,
            worktree_path=state.worktree_path,
            worktree_branch=state.worktree_branch,
            mode="agent" if chat_session is not None else state.mode,
            agent_type=state.agent_type,
            phase=state.phase,
            route_state=state.route_state,
            is_generating=state.is_generating,
            startup_error=startup_error if chat_session is None else state.startup_error,
            env_file=env_file_used or state.env_file,
            selected_file_path=state.selected_file_path,
            open_files=state.open_files,
            terminal_output=state.terminal_output,
            preview_url=state.preview_url or DEFAULT_BROWSER_PREVIEW_URL,
            interactive_command_session=interactive_command_session,
            chat_session=chat_session,
            history_messages=state.history_messages,
            history_tools=state.history_tools,
            code_changes=state.code_changes,
            thoughts=state.thoughts,
            token_usage=state.token_usage,
            cumulative_token_usage=state.cumulative_token_usage,
            max_context_tokens=context_limit if chat_session is not None else state.max_context_tokens,
            created_at=state.created_at,
            updated_at=state.updated_at,
            plan_steps=state.plan_steps,
            plan_state=state.plan_state,
            pending_delete_confirmations=state.pending_delete_confirmations,
            pending_commit_confirmations=state.pending_commit_confirmations,
            pending_tag_confirmations=state.pending_tag_confirmations,
            pending_user_input_requests=state.pending_user_input_requests,
            pending_connect_requests=state.pending_connect_requests,
            deploy_connection_manager=deploy_connection_manager,
            deploy_state=state.deploy_state,
        )
        session._ensure_default_terminal(state.workspace)
        if session.chat_session is not None:
            seed_chat_session_history(session.chat_session, state.history_messages, state.history_tools)
        if session.chat_session is not None:
            attach_agent_runtime_metadata(
                session.chat_session.agent,
                session_id=session.session_id,
                interactive_command_session=interactive_command_session,
                cancel_event=session.cancel_event,
                deploy_connection_manager=deploy_connection_manager,
            )
            sync_session_runtime_state_for_agent(session)
        return session

    def require_session(self, session_id: str) -> Any:
        session = self.sessions.get(session_id)
        if session is None:
            persisted_state = self.session_store.load(session_id)
            if persisted_state is None:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="session 不存在")
            session = self.hydrate_session_from_state(persisted_state)
            self.sessions[session_id] = session
        return session

    def stop_session_execution(self, session: Any) -> list[dict[str, Any]]:
        session.cancel_event.set()
        interactive_session = session.interactive_command_session
        if interactive_session is None:
            self.set_session_generating(session, False)
            return []
        terminated = interactive_session.terminate_all()
        self.set_session_generating(session, False)
        return terminated
