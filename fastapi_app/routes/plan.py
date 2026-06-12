from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from fastapi_app.agent_router import normalize_route_state
from fastapi_app.api_models import PlanDraftUpdateRequest, PlanSubmitRequest
from fastapi_app.runtime.session import (
    normalize_plan_state,
    set_session_phase,
    update_plan_state,
)


def _current_plan_from_state(plan_state: dict[str, Any]) -> dict[str, Any] | None:
    draft = plan_state.get("draft")
    if isinstance(draft, dict):
        return draft
    last_submitted_plan = plan_state.get("last_submitted_plan")
    if isinstance(last_submitted_plan, dict):
        return last_submitted_plan
    return None


def _resolve_plan_payload(
    session: Any,
    request: PlanSubmitRequest,
) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    base_plan = _current_plan_from_state(plan_state) or {}
    provided_fields = set(getattr(request, "model_fields_set", set()))

    def choose_text(field_name: str, fallback_key: str) -> str:
        if field_name in provided_fields:
            return str(getattr(request, field_name) or "").strip()
        return str(base_plan.get(fallback_key) or "").strip()

    title = choose_text("title", "title")
    summary = choose_text("summary", "summary")
    overview = choose_text("overview", "overview")
    markdown = choose_text("markdown", "markdown")
    if "keySteps" in provided_fields:
        key_steps = [item.strip() for item in request.keySteps if isinstance(item, str) and item.strip()]
    else:
        raw_key_steps = base_plan.get("keySteps")
        key_steps = [item.strip() for item in raw_key_steps if isinstance(item, str) and item.strip()] if isinstance(raw_key_steps, list) else []

    if not title or not summary or not overview or not key_steps or not markdown:
        raise HTTPException(status_code=400, detail="提交计划时必须至少提供 title、summary、overview、keySteps、markdown，或先生成计划草案。")

    return {
        "title": title,
        "summary": summary,
        "overview": overview,
        "keySteps": key_steps,
        "markdown": markdown,
    }


def _derive_plan_title_from_markdown(markdown: str, fallback: str = "计划草案") -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
        break
    return fallback


def update_current_plan_draft(
    session: Any,
    *,
    title: str | None,
    markdown: str,
    sync_session_runtime_state_for_agent: Callable[[Any], None],
) -> dict[str, Any]:
    normalized_markdown = str(markdown or "").strip()
    if not normalized_markdown:
        raise HTTPException(status_code=400, detail="markdown 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    base_plan = _current_plan_from_state(plan_state) or {}
    next_plan = dict(base_plan)
    resolved_title = str(title or next_plan.get("title") or "").strip() or _derive_plan_title_from_markdown(normalized_markdown)

    next_plan["title"] = resolved_title
    next_plan["markdown"] = normalized_markdown
    next_plan["summary"] = str(next_plan.get("summary") or "").strip()
    next_plan["overview"] = str(next_plan.get("overview") or "").strip()
    raw_key_steps = next_plan.get("keySteps")
    next_plan["keySteps"] = (
        [str(item).strip() for item in raw_key_steps if str(item).strip()]
        if isinstance(raw_key_steps, list)
        else []
    )

    status = str(plan_state.get("status") or "idle").strip().lower()
    update_plan_state(
        session,
        draft=next_plan,
        status="draft_ready" if status != "submitted" else status,
    )
    sync_session_runtime_state_for_agent(session)
    session.touch()
    return next_plan


def _build_coding_input_from_plan(plan: dict[str, Any]) -> str:
    lines = [
        "请根据下面这份已经确认的计划开始进入编码实现阶段。",
        "除非发现计划与现有代码现实冲突，否则不要重新回到需求澄清模式。",
        "",
        f"# {str(plan.get('title') or '').strip()}",
        str(plan.get("summary") or "").strip(),
        "",
        "## 总览",
        str(plan.get("overview") or "").strip(),
        "",
        "## 关键步骤",
    ]

    key_steps = plan.get("keySteps")
    if isinstance(key_steps, list):
        lines.extend(f"- {str(step).strip()}" for step in key_steps if str(step).strip())

    lines.extend(
        [
            "",
            "## 详细草案",
            str(plan.get("markdown") or "").strip(),
        ]
    )

    return "\n".join(line for line in lines if line is not None).strip()


def activate_plan_for_coding(
    session: Any,
    request: PlanSubmitRequest,
    *,
    rebuild_chat_session_for_agent_type: Callable[[Any, str], None],
    invalidate_session_context_usage: Callable[[Any], None],
    sync_session_runtime_state_for_agent: Callable[[Any], None],
) -> tuple[dict[str, Any], str]:
    plan = _resolve_plan_payload(session, request)
    coding_input = _build_coding_input_from_plan(plan)

    session.history_messages = []
    session.history_tools = []
    session.thoughts = []
    invalidate_session_context_usage(session)
    session.pending_user_input_requests.clear()
    session.pending_connect_requests.clear()
    session.pending_delete_confirmations.clear()
    session.pending_commit_confirmations.clear()
    session.pending_tag_confirmations.clear()
    update_plan_state(
        session,
        status="submitted",
        draft=plan,
        last_submitted_plan=plan,
        pending_coding_input=coding_input,
    )
    session.route_state = normalize_route_state(
        {
            "agentType": "coding",
            "confidence": 1.0,
            "reason": "计划已提交，自动切换到编码智能体执行计划。",
            "source": "forced",
            "fallbackUsed": False,
            "keepCurrentAgent": session.agent_type == "coding",
            "previousAgentType": session.agent_type,
        }
    )
    rebuild_chat_session_for_agent_type(session, "coding")
    session.plan_steps = []
    set_session_phase(session, "idle")
    sync_session_runtime_state_for_agent(session)
    session.touch()
    return plan, coding_input


def register_plan_routes(
    app: FastAPI,
    *,
    require_session: Callable[[str], Any],
    rebuild_chat_session_for_agent_type: Callable[[Any, str], None],
    invalidate_session_context_usage: Callable[[Any], None],
    sync_session_runtime_state_for_agent: Callable[[Any], None],
) -> None:
    @app.get("/api/sessions/{session_id}/plan-draft/current")
    async def get_current_plan_draft(session_id: str) -> JSONResponse:
        session = require_session(session_id)
        plan_state = normalize_plan_state(session.plan_state)
        plan = _current_plan_from_state(plan_state)
        if not isinstance(plan, dict):
            raise HTTPException(status_code=404, detail="当前会话没有可读取的计划草案。")

        return JSONResponse(
            {
                "ok": True,
                "plan": plan,
                "planState": session.plan_state,
            }
        )

    @app.post("/api/sessions/{session_id}/plan-draft")
    async def save_current_plan_draft(
        session_id: str,
        request: PlanDraftUpdateRequest,
    ) -> JSONResponse:
        session = require_session(session_id)
        plan = update_current_plan_draft(
            session,
            title=request.title,
            markdown=request.markdown,
            sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
        )
        return JSONResponse(
            {
                "ok": True,
                "plan": plan,
                "planState": session.plan_state,
            }
        )

    @app.post("/api/sessions/{session_id}/plan/submit")
    async def submit_plan(
        session_id: str,
        request: PlanSubmitRequest,
    ) -> JSONResponse:
        session = require_session(session_id)
        plan, coding_input = activate_plan_for_coding(
            session,
            request,
            rebuild_chat_session_for_agent_type=rebuild_chat_session_for_agent_type,
            invalidate_session_context_usage=invalidate_session_context_usage,
            sync_session_runtime_state_for_agent=sync_session_runtime_state_for_agent,
        )
        return JSONResponse(
            {
                "ok": True,
                "agentType": session.agent_type,
                "phase": session.phase,
                "routeState": session.route_state,
                "planState": session.plan_state,
                "plan": plan,
                "codingInput": coding_input,
                "shouldStartCoding": True,
            }
        )

