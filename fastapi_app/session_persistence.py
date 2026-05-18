from __future__ import annotations

from typing import Any

from fastapi_app.api_models import SessionHistoryItem
from fastapi_app.session_store import PersistedSessionState


def session_has_persistable_history(session: Any) -> bool:
    if session.history_messages:
        return True
    if session.history_tools:
        return True
    if session.thoughts:
        return True
    return False


def persist_session_state(session: Any, session_store: Any) -> None:
    if not session_has_persistable_history(session):
        try:
            session_store.delete(session.session_id)
        except Exception:
            pass
        return
    try:
        session_store.save(session_to_persisted_state(session))
    except Exception:
        # Persistence must not interrupt the streaming path.
        pass


def set_session_generating(session: Any, is_generating: bool) -> None:
    if session.is_generating == is_generating:
        return
    session.is_generating = is_generating
    session.touch()


def session_to_persisted_state(session: Any) -> PersistedSessionState:
    return PersistedSessionState(
        session_id=session.session_id,
        workspace=session.workspace,
        mode=session.mode,
        model=session.model,
        agent_type=session.agent_type,
        phase=session.phase,
        title=session.summary_title(),
        preview=session.summary_preview(),
        message_count=len(session.history_messages),
        tool_call_count=len(session.history_tools),
        created_at=session.created_at,
        updated_at=session.updated_at,
        is_generating=session.is_generating,
        startup_error=session.startup_error,
        env_file=session.env_file,
        selected_file_path=session.selected_file_path,
        open_files=session.open_files,
        terminal_output=session.terminal_output,
        preview_url=session.preview_url,
        history_messages=session.history_messages,
        history_tools=session.history_tools,
        thoughts=session.thoughts,
        plan_steps=session.plan_steps,
        pending_delete_confirmations=session.pending_delete_confirmations,
        pending_commit_confirmations=session.pending_commit_confirmations,
        pending_tag_confirmations=session.pending_tag_confirmations,
        pending_connect_requests=session.pending_connect_requests,
        deploy_connections=session.deploy_connection_manager.export_state(),
        deploy_state=session.deploy_state,
    )


def persisted_state_to_history_item(state: PersistedSessionState) -> SessionHistoryItem:
    return SessionHistoryItem(
        sessionId=state.session_id,
        workspace=state.workspace,
        mode=state.mode,
        model=state.model,
        agentType=state.agent_type,
        phase=state.phase,
        title=state.title,
        preview=state.preview,
        messageCount=state.message_count,
        toolCallCount=state.tool_call_count,
        createdAt=state.created_at,
        updatedAt=state.updated_at,
    )
