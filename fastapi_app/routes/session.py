from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from coding_agent.git_tools import init_git_repo
from fastapi_app.api_models import CreateSessionRequest, SessionCleanupRequest
from fastapi_app.internal_git_history import delete_workspace_session_history
from fastapi_app.workspace_utils import build_default_open_files, pick_default_file


@dataclass(frozen=True)
class SessionRouteDeps:
    session_registry: Any
    normalize_workspace: Callable[[str | None], str]
    normalize_execution_mode: Callable[[str | None], str]
    normalize_agent_type: Callable[[str | None], str]
    normalize_reasoning_effort: Callable[[str | None], str | None]
    resolve_requested_env_file: Callable[[str | None, str | None], str | None]
    build_chat_session: Callable[..., tuple[Any, str, str | None, str | None, str | None, int | None]]
    resolve_workspace_path: Callable[[str], Any]
    interactive_command_session_factory: Callable[[str], Any]
    attach_agent_runtime_metadata: Callable[..., None]
    sync_session_runtime_state_for_agent: Callable[[Any], None]
    list_workspace_options: Callable[[], list[dict[str, str]]]
    list_available_skill_summaries: Callable[[str], list[dict[str, Any]]]
    create_session_response_factory: Callable[..., Any]
    create_session_worktree: Callable[..., Any]
    worktree_runtime_deps: Any


def _build_session_snapshot_fallback(
    session: Any,
    *,
    deps: SessionRouteDeps,
    include_reasoning_effort: bool = True,
) -> Any:
    return deps.create_session_response_factory(
        sessionId=session.session_id,
        model=session.model,
        reasoningEffort=session.reasoning_effort if include_reasoning_effort else None,
        mode=session.mode,
        executionMode=session.execution_mode,
        baseWorkspace=session.base_workspace,
        worktreePath=session.worktree_path,
        worktreeBranch=session.worktree_branch,
        agentType=session.agent_type,
        phase=session.phase,
        routeState=session.route_state,
        deployState=session.deploy_state,
        planState=session.plan_state,
        isGenerating=session.is_generating,
        startupError=session.startup_error,
        envFile=session.env_file,
        workspace=session.workspace,
        workspaceOptions=deps.list_workspace_options(),
        messages=session.history_messages,
        toolCalls=session.history_tools,
        thoughts=session.thoughts,
        terminalOutput=session.terminal_output,
        previewUrl=session.preview_url,
        fileTree=[],
        fileTreeRevision=session.file_tree_revision,
        selectedFilePath=session.selected_file_path,
        selectedFileContent="",
        openFiles=session.open_files,
        availableSkills=deps.list_available_skill_summaries(session.workspace),
        codeChanges=session.code_changes,
        planSteps=session.plan_steps,
    )


def register_session_routes(
    app: FastAPI,
    *,
    deps: SessionRouteDeps,
) -> None:
    def close_runtime_session(session_id: str) -> None:
        session = deps.session_registry.sessions.pop(session_id, None)
        if session is None:
            return
        deps.session_registry.stop_session_execution(session)
        for runtime in session.terminal_runtimes.values():
            runtime.close()
        if session.interactive_command_session is not None:
            session.interactive_command_session.close()

    def cleanup_candidates(request: SessionCleanupRequest) -> tuple[list[Any], int]:
        states = deps.session_registry.session_store.list(limit=None)
        active_ids = set(deps.session_registry.sessions)
        selected_ids = {str(session_id).strip() for session_id in request.sessionIds if str(session_id).strip()}
        now_ms = int(time.time() * 1000)
        cutoff_ms: int | None = None
        if request.mode == "older_than":
            days = int(request.days or 0)
            if days <= 0:
                raise HTTPException(status_code=400, detail="清理天数必须大于 0")
            cutoff_ms = now_ms - days * 86_400_000
        if request.mode == "workspace" and not str(request.workspace or "").strip():
            raise HTTPException(status_code=400, detail="请选择要清理的工作区")

        candidates: list[Any] = []
        protected_active = 0
        for state in states:
            session_id = state.session_id
            workspace_key = str(state.base_workspace or state.workspace or "").strip()
            matched = False
            if request.mode == "older_than":
                matched = cutoff_ms is not None and int(state.updated_at or 0) < cutoff_ms
            elif request.mode == "workspace":
                matched = workspace_key == str(request.workspace or "").strip()
            elif request.mode == "empty":
                matched = state.message_count <= 0 and state.tool_call_count <= 0
            elif request.mode == "ids":
                matched = session_id in selected_ids
            elif request.mode == "all":
                matched = True
            if not matched:
                continue
            if session_id in active_ids and not request.includeActive:
                protected_active += 1
                continue
            candidates.append(state)
        return candidates, protected_active

    @app.post("/api/sessions")
    async def create_session(request: CreateSessionRequest) -> JSONResponse:
        session_id = uuid.uuid4().hex
        workspace = deps.normalize_workspace(request.workspace)
        execution_mode = deps.normalize_execution_mode(request.execution_mode)
        base_workspace = workspace
        worktree_path: str | None = None
        worktree_branch: str | None = None
        if execution_mode == "worktree":
            location = await asyncio.to_thread(
                deps.create_session_worktree,
                session_id=session_id,
                source_workspace=workspace,
                base_workspace=base_workspace,
                deps=deps.worktree_runtime_deps,
            )
            workspace = location.workspace
            base_workspace = location.base_workspace
            worktree_path = location.worktree_path
            worktree_branch = location.worktree_branch
        agent_type = deps.normalize_agent_type(request.agent_type)
        requested_env_file = deps.resolve_requested_env_file(request.model, request.env_file)
        try:
            reasoning_effort = deps.normalize_reasoning_effort(request.reasoning_effort)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            (
                chat_session,
                model_name,
                startup_error,
                env_file_used,
                resolved_reasoning_effort,
                context_limit,
            ) = await asyncio.wait_for(
                asyncio.to_thread(
                    deps.build_chat_session,
                    workspace,
                    requested_env_file,
                    agent_type,
                    reasoning_effort,
                    set(),
                    load_mcp_tools=False,
                ),
                timeout=30,
            )
        except asyncio.TimeoutError:
            chat_session, model_name, startup_error, env_file_used, resolved_reasoning_effort, context_limit = (
                None,
                "Demo",
                "初始化模型超时",
                None,
                reasoning_effort,
                None,
            )

        interactive_command_session = deps.interactive_command_session_factory(workspace)

        workspace_path = deps.resolve_workspace_path(workspace)
        should_auto_init_git = workspace_path.parent != workspace_path
        if request.initialize_git_repository and should_auto_init_git and not (workspace_path / ".git").exists():
            try:
                await asyncio.to_thread(init_git_repo, workspace_path)
            except Exception:
                pass

        session = deps.session_registry.session_factory(
            session_id=session_id,
            model=model_name,
            reasoning_effort=resolved_reasoning_effort,
            workspace=workspace,
            execution_mode=execution_mode,
            base_workspace=base_workspace,
            worktree_path=worktree_path,
            worktree_branch=worktree_branch,
            env_file=env_file_used,
            agent_type=agent_type,
            interactive_command_session=interactive_command_session,
            chat_session=chat_session,
            mode="agent" if chat_session is not None else "demo",
            startup_error=startup_error,
            selected_file_path=pick_default_file(workspace),
            open_files=build_default_open_files(workspace),
            max_context_tokens=context_limit,
        )
        session._ensure_default_terminal(workspace)
        if session.chat_session is not None:
            deps.attach_agent_runtime_metadata(
                session.chat_session.agent,
                session_id=session.session_id,
                interactive_command_session=interactive_command_session,
                cancel_event=session.cancel_event,
                deploy_connection_manager=session.deploy_connection_manager,
            )
            deps.sync_session_runtime_state_for_agent(session)
        deps.session_registry.register(session)
        deps.session_registry.persist_session_state(session)

        try:
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(session.snapshot),
                timeout=15,
            )
        except asyncio.TimeoutError:
            snapshot = _build_session_snapshot_fallback(session, deps=deps, include_reasoning_effort=True)
        return JSONResponse(snapshot.model_dump())

    @app.get("/api/sessions/history")
    async def get_session_history(
        limit: int = Query(30, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        def load_history_page() -> tuple[list[Any], int]:
            store = deps.session_registry.session_store
            return store.list(limit=limit, offset=offset), store.count()

        states, total = await asyncio.to_thread(load_history_page)
        history = [
            deps.session_registry.persisted_state_to_history_item(state).model_dump()
            for state in states
        ]
        return JSONResponse(
            {
                "sessions": history,
                "limit": limit,
                "offset": offset,
                "total": total,
                "hasMore": offset + len(history) < total,
            }
        )

    @app.get("/api/sessions/storage")
    async def get_session_storage_overview() -> JSONResponse:
        overview = await asyncio.to_thread(
            deps.session_registry.session_store.storage_overview,
            set(deps.session_registry.sessions),
        )
        return JSONResponse(overview)

    @app.post("/api/sessions/cleanup")
    async def cleanup_sessions(request: SessionCleanupRequest) -> JSONResponse:
        candidates, protected_active = await asyncio.to_thread(cleanup_candidates, request)
        candidate_ids = [state.session_id for state in candidates]
        summary = await asyncio.to_thread(
            deps.session_registry.session_store.summarize_session_ids,
            candidate_ids,
        )
        candidate_items = [
            {
                **deps.session_registry.persisted_state_to_history_item(state).model_dump(),
                "isActive": state.session_id in deps.session_registry.sessions,
            }
            for state in candidates[:200]
        ]
        deleted_ids: list[str] = []
        if not request.dryRun:
            for state in candidates:
                session_id = state.session_id
                close_runtime_session(session_id)
                try:
                    delete_workspace_session_history(state.workspace, session_id)
                except Exception:
                    pass
                deps.session_registry.session_store.delete(session_id)
                deleted_ids.append(session_id)
        return JSONResponse(
            {
                "dryRun": request.dryRun,
                "deletedCount": len(deleted_ids),
                "deletedSessionIds": deleted_ids,
                "candidateCount": len(candidate_ids),
                "protectedActiveCount": protected_active,
                "summary": summary,
                "candidates": candidate_items,
                "candidatePreviewLimit": 200,
            }
        )

    @app.get("/api/sessions/{session_id}")
    async def get_session_snapshot(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        try:
            snapshot = await asyncio.wait_for(asyncio.to_thread(session.snapshot), timeout=15)
        except asyncio.TimeoutError:
            snapshot = _build_session_snapshot_fallback(session, deps=deps, include_reasoning_effort=False)
        return JSONResponse(snapshot.model_dump())

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> JSONResponse:
        active_session = deps.session_registry.sessions.get(session_id)
        persisted_state = None
        if active_session is None:
            persisted_state = deps.session_registry.session_store.load(session_id)
            if persisted_state is None:
                raise HTTPException(status_code=404, detail="session 不存在")
        workspace_for_cleanup = (
            active_session.workspace
            if active_session is not None
            else persisted_state.workspace
            if persisted_state is not None
            else ""
        )
        close_runtime_session(session_id)
        if workspace_for_cleanup:
            try:
                delete_workspace_session_history(workspace_for_cleanup, session_id)
            except Exception:
                pass
        deps.session_registry.session_store.delete(session_id)
        return JSONResponse({"deleted": True, "sessionId": session_id})

    @app.post("/api/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        terminated = deps.session_registry.stop_session_execution(session)
        remaining = (
            session.interactive_command_session.list_managed_processes(only_active=True)
            if session.interactive_command_session is not None
            else []
        )
        return JSONResponse(
            {
                "stopped": True,
                "terminatedCount": len(terminated),
                "terminated": terminated,
                "remaining": remaining,
            }
        )

    @app.get("/api/sessions/{session_id}/processes")
    async def get_session_processes(
        session_id: str,
        active_only: bool = Query(True),
    ) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        interactive_session = session.interactive_command_session
        if interactive_session is None:
            return JSONResponse({"processes": []})
        processes = interactive_session.list_managed_processes(only_active=active_only)
        return JSONResponse({"processes": processes})

    @app.post("/api/sessions/{session_id}/processes/{terminal_id}/terminate")
    async def terminate_session_process(session_id: str, terminal_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        interactive_session = session.interactive_command_session
        if interactive_session is None:
            raise HTTPException(status_code=404, detail="当前会话没有受管进程")
        try:
            result = interactive_session.terminate_command(terminal_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        session.touch()
        return JSONResponse({"terminated": True, "process": result})
