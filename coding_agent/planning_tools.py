from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from zonix.tools import ToolContext


def _session_endpoint(ctx: ToolContext, suffix: str) -> str:
    backend_base_url = str(ctx.metadata.get("backend_base_url") or "").rstrip("/")
    session_id = str(ctx.metadata.get("session_id") or "").strip()
    if not backend_base_url or not session_id:
        raise RuntimeError("缺少 backend_base_url 或 session_id，无法访问当前会话。")
    return f"{backend_base_url}/api/sessions/{session_id}/{suffix.lstrip('/')}"


def _request_backend_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        method=method,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "SuperCode/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"请求失败：HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"请求失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("请求超时。") from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"返回了无法解析的 JSON：{raw_body[:300]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("返回格式不正确。")
    return parsed


def read_current_plan(ctx: ToolContext) -> dict[str, Any]:
    """读取当前会话中最新的计划草案/计划正文。"""

    payload = _request_backend_json(
        method="GET",
        url=_session_endpoint(ctx, "plan-draft/current"),
    )
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        raise RuntimeError("当前会话没有可读取的计划草案。")
    return {
        "plan": plan,
        "planState": payload.get("planState"),
    }


def create_task(
    ctx: ToolContext,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
) -> dict[str, Any]:
    """创建一个结构化 task。"""

    title = title.strip()
    summary = summary.strip()
    if not title:
        raise ValueError("title 不能为空。")
    if not summary:
        raise ValueError("summary 不能为空。")
    if not steps:
        raise ValueError("steps 不能为空。")

    normalized_steps: list[dict[str, str]] = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            raise ValueError("steps 里的每一项都必须是对象。")
        step_title = str(raw_step.get("title") or "").strip()
        step_summary = str(raw_step.get("summary") or "").strip()
        if not step_title or not step_summary:
            raise ValueError("每个 step 都必须包含 title 和 summary。")
        normalized_steps.append({"title": step_title, "summary": step_summary})

    payload = _request_backend_json(
        method="POST",
        url=_session_endpoint(ctx, "tasks"),
        payload={"title": title, "summary": summary, "steps": normalized_steps},
    )
    return {
        "task_id": payload.get("task_id"),
        "step_ids": payload.get("step_ids"),
        "task": payload.get("task"),
        "planState": payload.get("planState"),
        "planSteps": payload.get("planSteps"),
    }


def finish_task(ctx: ToolContext, step_id: str) -> dict[str, Any]:
    """完成当前正在执行的 step。"""

    step_id = step_id.strip()
    if not step_id:
        raise ValueError("step_id 不能为空。")
    payload = _request_backend_json(
        method="POST",
        url=_session_endpoint(ctx, "tasks/finish"),
        payload={"step_id": step_id},
    )
    return {
        "task_id": payload.get("task_id"),
        "step_id": payload.get("step_id"),
        "finished": payload.get("finished"),
        "next_step_id": payload.get("next_step_id"),
        "planState": payload.get("planState"),
        "planSteps": payload.get("planSteps"),
    }


def get_task_status(ctx: ToolContext, task_id: str = "") -> dict[str, Any]:
    """获取当前会话里的 task 状态。"""

    task_id = task_id.strip()
    query = f"?{urlencode({'task_id': task_id})}" if task_id else ""
    payload = _request_backend_json(
        method="GET",
        url=_session_endpoint(ctx, f"tasks/status{query}"),
    )
    return {
        "active_task_id": payload.get("active_task_id"),
        "active_step_id": payload.get("active_step_id"),
        "active_task": payload.get("active_task"),
        "tasks": payload.get("tasks"),
        "planState": payload.get("planState"),
        "planSteps": payload.get("planSteps"),
    }


read_current_plan.supports_parallel = True
