from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from fastapi_app.api_models import (
    CreateTaskRequest,
    FinishTaskRequest,
    SessionContextCompressionRequest,
    SessionRestoreRequest,
)


@dataclass(frozen=True)
class SessionOpsRouteDeps:
    require_session: Callable[[str], Any]
    create_task_in_session: Callable[..., dict[str, Any]]
    finish_task_step_in_session: Callable[[Any, str], dict[str, Any]]
    clear_task_plan_in_session: Callable[[Any], None]
    build_task_status_payload: Callable[[Any, str | None], dict[str, Any]]
    session_has_pending_context_interaction: Callable[[Any], bool]
    compress_session_context: Callable[..., Any]
    context_runtime_deps: Any
    fork_session_from_current: Callable[..., Any]
    restore_session_to_message: Callable[..., Any]
    worktree_runtime_deps: Any


def register_session_ops_routes(
    app: FastAPI,
    *,
    deps: SessionOpsRouteDeps,
) -> None:
    @app.post("/api/sessions/{session_id}/tasks")
    async def create_task_endpoint(
        session_id: str,
        request: CreateTaskRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        task = deps.create_task_in_session(
            session,
            title=request.title,
            summary=request.summary,
            steps=[{"title": step.title, "summary": step.summary} for step in request.steps],
            source=session.agent_type,
        )
        return JSONResponse(
            {
                "ok": True,
                "task_id": task["id"],
                "step_ids": [str(step.get("id") or "") for step in task.get("steps", []) if isinstance(step, dict)],
                "task": task,
                "planState": session.plan_state,
                "planSteps": session.plan_steps,
            }
        )

    @app.post("/api/sessions/{session_id}/tasks/finish")
    async def finish_task_endpoint(
        session_id: str,
        request: FinishTaskRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        result = deps.finish_task_step_in_session(session, request.step_id)
        return JSONResponse(
            {
                "ok": True,
                **result,
                "planState": session.plan_state,
                "planSteps": session.plan_steps,
            }
        )

    @app.delete("/api/sessions/{session_id}/tasks")
    async def clear_task_plan_endpoint(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        deps.clear_task_plan_in_session(session)
        return JSONResponse(
            {
                "ok": True,
                "planState": session.plan_state,
                "planSteps": session.plan_steps,
            }
        )

    @app.get("/api/sessions/{session_id}/tasks/status")
    async def get_task_status_endpoint(
        session_id: str,
        task_id: str | None = Query(None),
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        return JSONResponse(
            {
                "ok": True,
                **deps.build_task_status_payload(session, task_id=task_id),
                "planState": session.plan_state,
                "planSteps": session.plan_steps,
            }
        )

    @app.get("/api/sessions/{session_id}/deploy/connections")
    async def list_deploy_connections(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        manager = session.deploy_connection_manager
        if manager is None:
            return JSONResponse({"connections": []})
        return JSONResponse({"connections": manager.list_connections()})

    @app.get("/api/sessions/{session_id}/context")
    async def get_session_context(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        return JSONResponse(session.context_snapshot().model_dump())

    @app.post("/api/sessions/{session_id}/context/compress")
    async def compress_session_context_endpoint(
        session_id: str,
        request: SessionContextCompressionRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if request.mode == "apply":
            if session.is_generating:
                raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能压缩上下文")
            if deps.session_has_pending_context_interaction(session):
                raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能压缩上下文")
        response = await asyncio.to_thread(
            deps.compress_session_context,
            session,
            request,
            deps=deps.context_runtime_deps,
        )
        return JSONResponse(response.model_dump())

    @app.post("/api/sessions/{session_id}/fork")
    async def fork_session_endpoint(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.is_generating:
            raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能派生分支")
        if deps.session_has_pending_context_interaction(session):
            raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能派生分支")
        forked_session = await asyncio.to_thread(
            deps.fork_session_from_current,
            session,
            deps=deps.worktree_runtime_deps,
        )
        snapshot = await asyncio.to_thread(forked_session.snapshot)
        return JSONResponse(snapshot.model_dump())

    @app.post("/api/sessions/{session_id}/restore")
    async def restore_session_endpoint(
        session_id: str,
        request: SessionRestoreRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.is_generating:
            raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能还原对话")
        if deps.session_has_pending_context_interaction(session):
            raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能还原对话")
        snapshot = await asyncio.to_thread(
            deps.restore_session_to_message,
            session,
            request.messageId,
            deps=deps.worktree_runtime_deps,
        )
        return JSONResponse(snapshot.model_dump())
