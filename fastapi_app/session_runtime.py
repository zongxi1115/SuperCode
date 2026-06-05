from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from fastapi_app.memory_store import build_long_term_memory_context
from fastapi_app.settings_store import load_settings
from fastapi_app.skills import list_available_skill_summaries


def normalize_session_phase(phase: str | None) -> str:
    normalized = str(phase or "idle").strip().lower()
    allowed = {
        "idle",
        "clarifying",
        "researching",
        "planning",
        "awaiting_user_input",
        "plan_ready",
        "submitted",
        "awaiting_connect_input",
        "connected",
        "exploring",
        "executing",
        "verifying",
        "completed",
        "failed",
    }
    return normalized if normalized in allowed else "idle"


def build_default_deploy_state() -> dict[str, Any]:
    return {
        "active_session_id": None,
        "active_root_path": None,
        "active_display_name": None,
        "active_host": None,
        "active_username": None,
        "active_extra_info": None,
        "pending_tool_id": None,
        "pending_tool_name": None,
        "pending_input_kind": None,
        "last_tool_name": None,
        "last_tool_state": None,
        "last_command": None,
        "last_command_cwd": None,
        "last_exit_code": None,
        "last_error": None,
        "last_message": None,
        "connection_count": 0,
        "known_session_ids": [],
    }


def normalize_deploy_state(value: object) -> dict[str, Any]:
    state = build_default_deploy_state()
    if isinstance(value, dict):
        for key in state:
            if key in value:
                state[key] = value[key]
    return state


def build_default_plan_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "draft": None,
        "last_submitted_plan": None,
        "pending_coding_input": None,
        "tasks": [],
        "active_task_id": None,
        "active_step_id": None,
    }


def _normalize_step_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    return normalized if normalized in {"pending", "running", "completed"} else "pending"


def _normalize_task_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    return normalized if normalized in {"pending", "running", "completed"} else "pending"


def _normalize_plan_tasks(raw_tasks: object) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []

    tasks: list[dict[str, Any]] = []
    for task_index, raw_task in enumerate(raw_tasks, start=1):
        if not isinstance(raw_task, dict):
            continue
        task_id = str(raw_task.get("id") or "").strip()
        title = str(raw_task.get("title") or "").strip()
        summary = str(raw_task.get("summary") or "").strip()
        source = str(raw_task.get("source") or "").strip() or "coding"
        raw_steps = raw_task.get("steps")
        if not task_id or not title or not summary or not isinstance(raw_steps, list):
            continue

        steps: list[dict[str, Any]] = []
        for step_index, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("id") or "").strip()
            step_title = str(raw_step.get("title") or "").strip()
            step_summary = str(raw_step.get("summary") or "").strip()
            if not step_id or not step_title or not step_summary:
                continue
            steps.append(
                {
                    "id": step_id,
                    "title": step_title,
                    "summary": step_summary,
                    "status": _normalize_step_status(raw_step.get("status")),
                    "order": int(raw_step.get("order") or step_index),
                }
            )

        if not steps:
            continue

        tasks.append(
            {
                "id": task_id,
                "title": title,
                "summary": summary,
                "status": _normalize_task_status(raw_task.get("status")),
                "source": source,
                "steps": steps,
                "order": int(raw_task.get("order") or task_index),
            }
        )

    return tasks


def _find_task_by_id(tasks: list[dict[str, Any]], task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    return next((task for task in tasks if str(task.get("id")) == task_id), None)


def _find_active_task(tasks: list[dict[str, Any]], active_task_id: str | None) -> dict[str, Any] | None:
    active_task = _find_task_by_id(tasks, active_task_id)
    if active_task is not None:
        return active_task
    return next((task for task in tasks if str(task.get("status")) == "running"), None)


def _derive_plan_steps_from_tasks(plan_state: dict[str, Any]) -> list[dict[str, str]]:
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    display_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if display_task is None and tasks:
        display_task = tasks[-1]
    if display_task is None:
        return []

    steps = display_task.get("steps")
    if not isinstance(steps, list):
        return []

    return [
        {
            "id": str(step.get("id") or ""),
            "title": str(step.get("title") or ""),
            "description": str(step.get("summary") or ""),
            "status": _normalize_step_status(step.get("status")),
        }
        for step in steps
        if isinstance(step, dict)
    ]


def _sync_plan_steps_from_tasks(session: Any) -> None:
    derived_steps = _derive_plan_steps_from_tasks(session.plan_state)
    if derived_steps:
        session.plan_steps = derived_steps


def ensure_deploy_plan_steps(session: Any) -> None:
    if session.agent_type != "deploy" or session.plan_steps:
        return
    session.plan_steps = [
        {
            "id": "deploy-connect",
            "title": "连接部署目标",
            "description": "选择或填写部署目标信息，准备建立部署连接。",
            "status": "running",
        },
        {
            "id": "deploy-explore",
            "title": "探索部署目录",
            "description": "读取部署目录、配置文件和发布脚本，确认发布方式。",
            "status": "pending",
        },
        {
            "id": "deploy-execute",
            "title": "执行部署命令",
            "description": "同步文件或执行部署命令，并收集部署结果。",
            "status": "pending",
        },
    ]


def _build_task_payload(
    *,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
    source: str,
    order: int,
) -> dict[str, Any]:
    task_id = f"task_{uuid.uuid4().hex[:10]}"
    normalized_steps = [
        {
            "id": f"step_{uuid.uuid4().hex[:10]}",
            "title": str(step.get("title") or "").strip(),
            "summary": str(step.get("summary") or "").strip(),
            "status": "running" if index == 0 else "pending",
            "order": index + 1,
        }
        for index, step in enumerate(steps)
    ]
    return {
        "id": task_id,
        "title": title,
        "summary": summary,
        "status": "running",
        "source": source,
        "steps": normalized_steps,
        "order": order,
    }


def create_task_in_session(
    session: Any,
    *,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
    source: str,
) -> dict[str, Any]:
    normalized_title = str(title or "").strip()
    normalized_summary = str(summary or "").strip()
    normalized_steps = [
        {
            "title": str(step.get("title") or "").strip(),
            "summary": str(step.get("summary") or "").strip(),
        }
        for step in steps
        if str(step.get("title") or "").strip() and str(step.get("summary") or "").strip()
    ]
    if not normalized_title:
        raise HTTPException(status_code=400, detail="title 不能为空。")
    if not normalized_summary:
        raise HTTPException(status_code=400, detail="summary 不能为空。")
    if not normalized_steps:
        raise HTTPException(status_code=400, detail="steps 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    previous_active_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if previous_active_task is not None:
        previous_active_task["status"] = "pending"
        for step in previous_active_task.get("steps", []):
            if isinstance(step, dict) and str(step.get("status")) == "running":
                step["status"] = "pending"

    task = _build_task_payload(
        title=normalized_title,
        summary=normalized_summary,
        steps=normalized_steps,
        source=source,
        order=len(tasks) + 1,
    )
    tasks.append(task)
    task_steps = task.get("steps")
    if not task_steps:
        raise HTTPException(status_code=400, detail="创建的 task 至少需要一个 step。")
    first_step = task_steps[0]
    update_plan_state(
        session,
        tasks=tasks,
        active_task_id=task["id"],
        active_step_id=first_step["id"],
    )
    session.touch()
    return task


def finish_task_step_in_session(session: Any, step_id: str) -> dict[str, Any]:
    normalized_step_id = str(step_id or "").strip()
    if not normalized_step_id:
        raise HTTPException(status_code=400, detail="step_id 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    active_step_id = str(plan_state.get("active_step_id") or "").strip()
    if active_step_id != normalized_step_id:
        raise HTTPException(status_code=409, detail="只能完成当前正在执行的 step。")

    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    active_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if active_task is None:
        raise HTTPException(status_code=404, detail="当前没有可完成的 task。")

    steps = active_task.get("steps")
    if not isinstance(steps, list):
        raise HTTPException(status_code=404, detail="当前 task 没有 steps。")

    current_index = next(
        (index for index, step in enumerate(steps) if str(step.get("id")) == normalized_step_id),
        None,
    )
    if current_index is None:
        raise HTTPException(status_code=404, detail="step_id 不存在。")

    current_step = steps[current_index]
    current_step["status"] = "completed"
    next_step_id: str | None = None
    next_index = current_index + 1
    if next_index < len(steps):
        next_step = steps[next_index]
        next_step["status"] = "running"
        active_task["status"] = "running"
        next_step_id = str(next_step.get("id") or "").strip() or None
    else:
        active_task["status"] = "completed"

    update_plan_state(
        session,
        tasks=tasks,
        active_task_id=(str(active_task.get("id") or "").strip() if next_step_id else None),
        active_step_id=next_step_id,
    )
    session.touch()
    return {
        "task_id": str(active_task.get("id") or ""),
        "step_id": normalized_step_id,
        "finished": True,
        "next_step_id": next_step_id,
    }


def build_task_status_payload(session: Any, task_id: str | None = None) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    active_task_id = str(plan_state.get("active_task_id") or "").strip() or None
    active_step_id = str(plan_state.get("active_step_id") or "").strip() or None
    active_task = _find_task_by_id(tasks, task_id) if task_id else _find_active_task(tasks, active_task_id)
    if active_task is None and tasks:
        active_task = tasks[-1]
    return {
        "active_task_id": active_task_id,
        "active_step_id": active_step_id,
        "active_task": active_task,
        "tasks": tasks,
    }


def normalize_plan_state(value: object) -> dict[str, Any]:
    state = build_default_plan_state()
    if isinstance(value, dict):
        for key in state:
            if key in value:
                state[key] = value[key]
    if not isinstance(state.get("draft"), dict):
        state["draft"] = None
    if not isinstance(state.get("last_submitted_plan"), dict):
        state["last_submitted_plan"] = None
    pending_coding_input = state.get("pending_coding_input")
    state["pending_coding_input"] = (
        str(pending_coding_input).strip() if isinstance(pending_coding_input, str) else None
    )
    state["tasks"] = _normalize_plan_tasks(state.get("tasks"))
    active_task = _find_active_task(state["tasks"], str(state.get("active_task_id") or "").strip() or None)
    state["active_task_id"] = str(active_task.get("id") or "").strip() if active_task else None
    active_step_id = str(state.get("active_step_id") or "").strip() or None
    if active_task is None:
        state["active_step_id"] = None
    else:
        steps = active_task.get("steps")
        if isinstance(steps, list) and any(str(step.get("id")) == active_step_id for step in steps if isinstance(step, dict)):
            state["active_step_id"] = active_step_id
        else:
            running_step = next(
                (
                    step
                    for step in steps
                    if isinstance(step, dict) and str(step.get("status")) == "running"
                ),
                None,
            )
            state["active_step_id"] = str(running_step.get("id") or "").strip() if running_step else None
    status = str(state.get("status") or "idle").strip().lower()
    if status not in {"idle", "clarifying", "researching", "planning", "awaiting_user_input", "draft_ready", "submitted"}:
        state["status"] = "idle"
    else:
        state["status"] = status
    return state


def refresh_session_runtime_state(session: Any) -> None:
    if session.agent_type == "plan":
        session.plan_state = normalize_plan_state(session.plan_state)
        _sync_plan_steps_from_tasks(session)
        session.deploy_state = normalize_deploy_state(session.deploy_state)
        if session.pending_user_input_requests:
            session.phase = "awaiting_user_input"
            session.plan_state["status"] = "awaiting_user_input"
            return
        if session.plan_state.get("status") in {"clarifying", "researching", "planning"}:
            session.phase = (
                "planning"
                if session.plan_state.get("status") == "planning"
                else str(session.plan_state.get("status"))
            )
            return
        if session.plan_state.get("draft"):
            session.phase = "plan_ready"
            if session.plan_state.get("status") != "submitted":
                session.plan_state["status"] = "draft_ready"
            return
        session.phase = normalize_session_phase(session.phase)
        if session.phase not in {"clarifying", "researching", "planning"}:
            session.phase = "clarifying"
        if session.plan_state.get("status") == "idle":
            session.plan_state["status"] = "clarifying"
        return

    if session.agent_type != "deploy":
        session.phase = "idle"
        session.plan_state = normalize_plan_state(session.plan_state)
        _sync_plan_steps_from_tasks(session)
        session.deploy_state = normalize_deploy_state(session.deploy_state)
        return

    session.phase = normalize_session_phase(session.phase)
    deploy_state = normalize_deploy_state(session.deploy_state)
    session.plan_state = normalize_plan_state(session.plan_state)
    _sync_plan_steps_from_tasks(session)
    ensure_deploy_plan_steps(session)
    manager = session.deploy_connection_manager
    connections = manager.list_connections() if manager is not None else []
    deploy_state["connection_count"] = len(connections)
    deploy_state["known_session_ids"] = [
        str(connection.get("session_id") or "")
        for connection in connections[:10]
        if str(connection.get("session_id") or "").strip()
    ]

    active_session_id = str(deploy_state.get("active_session_id") or "").strip()
    if active_session_id and manager is not None:
        try:
            active_connection = manager.get_connection(active_session_id)
        except KeyError:
            deploy_state["active_session_id"] = None
            deploy_state["active_root_path"] = None
            deploy_state["active_display_name"] = None
            deploy_state["active_host"] = None
            deploy_state["active_username"] = None
            deploy_state["active_extra_info"] = None
        else:
            if active_connection.host and not manager.has_password(active_session_id):
                deploy_state["active_session_id"] = None
                deploy_state["active_root_path"] = None
                deploy_state["active_display_name"] = None
                deploy_state["active_host"] = None
                deploy_state["active_username"] = None
                deploy_state["active_extra_info"] = None
            else:
                deploy_state["active_root_path"] = str(active_connection.root_path)
                deploy_state["active_display_name"] = active_connection.display_name
                deploy_state["active_host"] = active_connection.host or None
                deploy_state["active_username"] = active_connection.username or None
                deploy_state["active_extra_info"] = active_connection.extra_info or None

    pending_tool_id = str(deploy_state.get("pending_tool_id") or "").strip()
    pending_input_kind = str(deploy_state.get("pending_input_kind") or "").strip()
    if pending_tool_id and pending_input_kind and pending_tool_id not in session.pending_connect_requests:
        deploy_state["pending_tool_id"] = None
        deploy_state["pending_tool_name"] = None
        deploy_state["pending_input_kind"] = None

    session.deploy_state = deploy_state


def build_agent_runtime_state(session: Any, app_root: Path) -> dict[str, Any]:
    refresh_session_runtime_state(session)
    settings = load_settings(app_root)
    final_answer_rendering = (
        "html"
        if settings.get("finalAnswerRendering") == "html"
        else "markdown"
    )
    return {
        "agent_type": session.agent_type,
        "phase": session.phase,
        "workspace": session.workspace,
        "final_answer_rendering": final_answer_rendering,
        "execution_mode": session.execution_mode,
        "base_workspace": session.base_workspace,
        "worktree_path": session.worktree_path,
        "worktree_branch": session.worktree_branch,
        "route_state": session.route_state,
        "deploy_state": session.deploy_state if session.agent_type == "deploy" else {},
        "plan_state": session.plan_state,
    }


def sync_session_runtime_state_for_agent(session: Any, app_root: Path) -> None:
    if session.chat_session is None:
        return
    state = getattr(session.chat_session, "state", None)
    data = getattr(state, "data", None)
    if not isinstance(data, dict):
        return
    data["runtime_state"] = build_agent_runtime_state(session, app_root)
    data["available_skills"] = list_available_skill_summaries(session.workspace)
    data["long_term_memory"] = build_long_term_memory_context(app_root, session.workspace)


def set_session_phase(session: Any, phase: str) -> None:
    session.phase = normalize_session_phase(phase)


def update_deploy_state(session: Any, **updates: Any) -> None:
    if session.agent_type != "deploy":
        return
    deploy_state = normalize_deploy_state(session.deploy_state)
    for key, value in updates.items():
        if key in deploy_state:
            deploy_state[key] = value
    session.deploy_state = deploy_state
    refresh_session_runtime_state(session)


def update_plan_state(session: Any, **updates: Any) -> None:
    plan_state = normalize_plan_state(session.plan_state)
    for key, value in updates.items():
        if key in plan_state:
            plan_state[key] = value
    session.plan_state = normalize_plan_state(plan_state)
    refresh_session_runtime_state(session)


def reset_phase_for_new_turn(session: Any) -> None:
    if session.agent_type == "plan":
        refresh_session_runtime_state(session)
        if session.pending_user_input_requests:
            set_session_phase(session, "awaiting_user_input")
            update_plan_state(session, status="awaiting_user_input")
            return
        if session.plan_state.get("draft"):
            set_session_phase(session, "plan_ready")
            update_plan_state(session, status="draft_ready")
            return
        set_session_phase(session, "clarifying")
        update_plan_state(session, status="clarifying")
        return

    if session.agent_type != "deploy":
        set_session_phase(session, "idle")
        return

    refresh_session_runtime_state(session)
    if session.pending_connect_requests:
        set_session_phase(session, "awaiting_connect_input")
        return
    if session.deploy_state.get("active_session_id"):
        set_session_phase(session, "connected")
        return
    set_session_phase(session, "idle")

