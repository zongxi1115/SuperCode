from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from coding_agent.file_tools import delete_file_in_workspace
from coding_agent.git_tools import execute_git_commit, execute_git_tag
from fastapi_app.app_config import APP_DATA_ROOT
from fastapi_app.api_models import ConnectToolSubmitRequest, ToolConfirmationRequest, ToolInputSubmitRequest
from fastapi_app.code_changes import current_agent_turn_index, record_code_change
from fastapi_app.rag_index import schedule_workspace_rag_index
from fastapi_app.session_history import (
    record_confirmation_result_for_agent,
    record_tool_result_for_agent,
    update_assistant_tool_call,
    upsert_tool,
)
from fastapi_app.workspace_utils import normalize_relative_path, read_text_file, resolve_workspace_path


@dataclass(frozen=True)
class ToolInteractionRouteDeps:
    require_session: Callable[[str], Any]
    set_session_phase: Callable[[Any, str], None]
    update_deploy_state: Callable[..., None]
    update_plan_state: Callable[..., None]


def _normalize_tool_input_answers(
    input_request: dict[str, Any],
    request: ToolInputSubmitRequest,
) -> list[dict[str, Any]]:
    raw_questions = input_request.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise HTTPException(status_code=400, detail="当前输入请求缺少 questions。")

    questions_by_id: dict[str, dict[str, Any]] = {}
    question_order: list[str] = []
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            continue
        question_id = str(raw_question.get("id") or "").strip()
        if not question_id:
            continue
        questions_by_id[question_id] = raw_question
        question_order.append(question_id)

    answers_by_id = {
        answer.questionId.strip(): answer
        for answer in request.answers
        if answer.questionId.strip()
    }
    normalized_answers: list[dict[str, Any]] = []

    unknown_answers = sorted(set(answers_by_id) - set(questions_by_id))
    if unknown_answers:
        raise HTTPException(status_code=400, detail=f"存在未知问题 ID：{', '.join(unknown_answers)}")

    for question_id in question_order:
        question = questions_by_id[question_id]
        answer = answers_by_id.get(question_id)
        question_type = str(question.get("type") or "").strip()
        prompt = str(question.get("prompt") or "").strip()
        required = bool(question.get("required", True))
        other_text = ""
        selected_option_ids: list[str] = []
        free_text = ""

        if answer is not None:
            other_text = str(answer.otherText or "").strip()
            selected_option_ids = [
                option_id.strip()
                for option_id in answer.selectedOptionIds
                if option_id.strip()
            ]
            free_text = str(answer.text or "").strip()

        if question_type == "short_text":
            if required and not free_text:
                raise HTTPException(status_code=400, detail=f"问题「{prompt}」尚未回答。")
            normalized_answers.append(
                {
                    "questionId": question_id,
                    "type": question_type,
                    "prompt": prompt,
                    "text": free_text,
                    "otherText": other_text or None,
                }
            )
            continue

        raw_options = question.get("options")
        options = raw_options if isinstance(raw_options, list) else []
        options_by_id = {
            str(option.get("id") or "").strip(): option
            for option in options
            if isinstance(option, dict) and str(option.get("id") or "").strip()
        }

        invalid_option_ids = [option_id for option_id in selected_option_ids if option_id not in options_by_id]
        if invalid_option_ids:
            raise HTTPException(
                status_code=400,
                detail=f"问题「{prompt}」包含未知选项：{', '.join(invalid_option_ids)}",
            )
        if question_type == "single_choice" and len(selected_option_ids) > 1:
            raise HTTPException(status_code=400, detail=f"问题「{prompt}」只能选择一个选项。")
        if required and not selected_option_ids and not other_text:
            raise HTTPException(status_code=400, detail=f"问题「{prompt}」尚未回答。")

        normalized_answers.append(
            {
                "questionId": question_id,
                "type": question_type,
                "prompt": prompt,
                "selectedOptionIds": selected_option_ids,
                "selectedOptions": [
                    {
                        "id": option_id,
                        "label": str(options_by_id[option_id].get("label") or "").strip(),
                        "description": str(options_by_id[option_id].get("description") or "").strip(),
                    }
                    for option_id in selected_option_ids
                ],
                "otherText": other_text or None,
                "text": free_text or None,
            }
        )

    return normalized_answers


def _format_tool_input_answers_for_agent(
    title: str,
    answers: list[dict[str, Any]],
) -> str:
    lines = [f"[用户回答] {title}".strip()]
    for answer in answers:
        prompt = str(answer.get("prompt") or answer.get("questionId") or "未命名问题").strip()
        answer_type = str(answer.get("type") or "").strip()
        if answer_type == "short_text":
            value = str(answer.get("text") or answer.get("otherText") or "").strip() or "(未填写)"
        else:
            labels = [
                str(option.get("label") or "").strip()
                for option in answer.get("selectedOptions", [])
                if isinstance(option, dict) and str(option.get("label") or "").strip()
            ]
            other_text = str(answer.get("otherText") or "").strip()
            if other_text:
                labels.append(f"其他：{other_text}")
            value = "；".join(labels) if labels else "(未填写)"
        lines.append(f"- {prompt}: {value}")
    return "\n".join(lines)


def register_tool_interaction_routes(
    app: FastAPI,
    *,
    deps: ToolInteractionRouteDeps,
) -> None:
    @app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-delete")
    async def confirm_delete_tool(
        session_id: str,
        tool_id: str,
        request: ToolConfirmationRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        pending = session.pending_delete_confirmations.pop(tool_id, None)
        if pending is None:
            raise HTTPException(status_code=404, detail="未找到待确认的删除动作")

        filename = str(pending.get("filename") or "").strip()
        assistant_id = str(pending.get("assistant_id") or "").strip()
        if not filename:
            raise HTTPException(status_code=400, detail="待确认删除动作缺少 filename")

        approval = {"id": tool_id, "approved": request.approved}
        assistant_id = str(pending.get("assistant_id") or "").strip()
        if not request.approved:
            tool_record = {
                "id": tool_id,
                "output": "已取消删除。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 已取消：{filename}")
            session.touch()
            return JSONResponse(
                {
                    "id": tool_id,
                    "name": "delete_file",
                    "output": "已取消删除。",
                    "success": False,
                    "state": "output-denied",
                    "approval": approval,
                    "selectedFileCleared": False,
                    "assistantId": assistant_id,
                    "shouldContinue": bool(assistant_id),
                }
            )

        selected_file_cleared = False
        try:
            target = Path(normalize_relative_path(filename, session.workspace))
            before_text = read_text_file(str(target), session.workspace)
            output = delete_file_in_workspace(filename, resolve_workspace_path(session.workspace))
            session.mark_file_tree_dirty(paths=[target])
            if session.selected_file_path == normalize_relative_path(filename, session.workspace):
                session.selected_file_path = None
                selected_file_cleared = True
            tool_record = {
                "id": tool_id,
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 已确认并执行成功：{output}")
            code_change = record_code_change(
                session,
                action="deleted",
                path=target,
                before_text=before_text,
                after_text="",
                source="agent",
                tool_call_id=tool_id,
                assistant_id=assistant_id or None,
                turn_index=current_agent_turn_index(session),
                step_index=pending.get("step_index") if isinstance(pending.get("step_index"), int) else None,
            )
            schedule_workspace_rag_index(APP_DATA_ROOT, session.workspace)
            session.touch()
            return JSONResponse(
                {
                    "id": tool_id,
                    "name": "delete_file",
                    "output": output,
                    "success": True,
                    "state": "output-available",
                    "approval": approval,
                    "selectedFileCleared": selected_file_cleared,
                    "assistantId": assistant_id,
                    "shouldContinue": bool(assistant_id),
                    "codeChange": code_change,
                }
            )
        except Exception as exc:
            tool_record = {
                "id": tool_id,
                "output": None,
                "success": False,
                "state": "error",
                "errorMessage": str(exc),
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 执行失败：{exc}")
            session.touch()
            return JSONResponse(
                {
                    "id": tool_id,
                    "name": "delete_file",
                    "output": None,
                    "success": False,
                    "state": "error",
                    "error_message": str(exc),
                    "approval": approval,
                    "selectedFileCleared": False,
                    "assistantId": assistant_id,
                    "shouldContinue": bool(assistant_id),
                },
                status_code=500,
            )

    @app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-commit")
    async def confirm_commit_tool(
        session_id: str,
        tool_id: str,
        request: ToolConfirmationRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        pending = session.pending_commit_confirmations.pop(tool_id, None)
        if pending is None:
            raise HTTPException(status_code=404, detail="未找到待确认的提交动作")

        approval = {"id": tool_id, "approved": request.approved}
        assistant_id = str(pending.get("assistant_id") or "").strip()
        if not request.approved:
            tool_record = {
                "id": tool_id,
                "output": "已取消提交。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, "[内部确认结果] git_commit 已取消。")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_commit",
                "output": "已取消提交。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            })

        commit_message = str(pending.get("commit_message") or "")
        if not commit_message:
            raise HTTPException(status_code=400, detail="待确认提交动作缺少 commit_message")

        try:
            output = execute_git_commit(commit_message, resolve_workspace_path(session.workspace))
            session.mark_file_tree_dirty()
            tool_record = {
                "id": tool_id,
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] git_commit 已确认并执行成功：{output}")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_commit",
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            })
        except Exception as exc:
            tool_record = {
                "id": tool_id,
                "output": None,
                "success": False,
                "state": "error",
                "errorMessage": str(exc),
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] git_commit 执行失败：{exc}")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_commit",
                "output": None,
                "success": False,
                "state": "error",
                "error_message": str(exc),
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            }, status_code=500)

    @app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-tag")
    async def confirm_tag_tool(
        session_id: str,
        tool_id: str,
        request: ToolConfirmationRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        pending = session.pending_tag_confirmations.pop(tool_id, None)
        if pending is None:
            raise HTTPException(status_code=404, detail="未找到待确认的标签动作")

        approval = {"id": tool_id, "approved": request.approved}
        assistant_id = str(pending.get("assistant_id") or "").strip()
        if not request.approved:
            tool_record = {
                "id": tool_id,
                "output": "已取消创建标签。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, "[内部确认结果] git_tag 已取消。")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_tag",
                "output": "已取消创建标签。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            })

        tag_name = str(pending.get("tag") or "")
        tag_message = str(pending.get("tag_message") or f"Release {tag_name}")
        if not tag_name:
            raise HTTPException(status_code=400, detail="待确认标签动作缺少 tag")

        try:
            output = execute_git_tag(tag_name, tag_message, resolve_workspace_path(session.workspace))
            tool_record = {
                "id": tool_id,
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] git_tag 已确认并执行成功：{output}")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_tag",
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            })
        except Exception as exc:
            tool_record = {
                "id": tool_id,
                "output": None,
                "success": False,
                "state": "error",
                "errorMessage": str(exc),
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            record_confirmation_result_for_agent(session, f"[内部确认结果] git_tag 执行失败：{exc}")
            session.touch()
            return JSONResponse({
                "id": tool_id,
                "name": "git_tag",
                "output": None,
                "success": False,
                "state": "error",
                "error_message": str(exc),
                "approval": approval,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            }, status_code=500)

    @app.post("/api/sessions/{session_id}/tools/{tool_id}/connect")
    async def submit_connect_tool(
        session_id: str,
        tool_id: str,
        request: ConnectToolSubmitRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        pending = session.pending_connect_requests.get(tool_id)
        if pending is None:
            raise HTTPException(status_code=404, detail="未找到待填写的 connect 请求")

        deploy_manager = session.deploy_connection_manager
        if deploy_manager is None:
            raise HTTPException(status_code=500, detail="当前会话缺少 deploy connection manager")

        values = request.values if isinstance(request.values, dict) else {}
        host = str(values.get("host") or "").strip()
        username = str(values.get("username") or "").strip()
        password = str(values.get("password") or "")
        root_path = str(values.get("root_path") or "").strip()
        display_name = str(values.get("display_name") or "").strip()
        description = str(values.get("description") or "").strip()
        extra_info = str(values.get("extra_info") or "").strip()
        if not root_path:
            raise HTTPException(status_code=400, detail="root_path 为必填项")
        if host and (not username or not password):
            raise HTTPException(status_code=400, detail="远程连接必须提供 username 和 password")

        try:
            connection = deploy_manager.create_connection(
                root_path=root_path,
                display_name=display_name,
                description=description,
                extra_info=extra_info,
                host=host,
                username=username,
                password=password,
            )
        except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        session.pending_connect_requests.pop(tool_id, None)
        assistant_id = str(pending.get("assistant_id") or "").strip()
        can_continue = bool(assistant_id and session.chat_session is not None)
        input_request = pending.get("request") if isinstance(pending.get("request"), dict) else None
        output = {
            **connection,
            "message": (
                f"已建立 deploy session {connection['session_id']}，"
                + (f"服务器：{connection['host']}" if connection.get("host") else f"根目录：{connection['root_path']}")
            ),
        }
        tool_record = {
            "id": tool_id,
            "name": str(pending.get("tool_name") or "connect"),
            "output": output,
            "success": True,
            "state": "output-available",
            "inputRequest": input_request,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        if assistant_id:
            update_assistant_tool_call(
                session,
                assistant_id,
                tool_id,
                lambda existing: {
                    **existing,
                    **tool_record,
                },
            )
        record_confirmation_result_for_agent(
            session,
            (
                "[内部连接结果] connect 已建立 deploy session："
                f"{connection['session_id']} -> {connection['root_path']}"
            ),
        )
        deps.set_session_phase(session, "connected")
        deps.update_deploy_state(
            session,
            active_session_id=connection["session_id"],
            active_root_path=connection["root_path"],
            active_display_name=connection["display_name"],
            active_host=connection.get("host") or None,
            active_username=connection.get("username") or None,
            active_extra_info=connection.get("extra_info") or None,
            pending_tool_id=None,
            pending_tool_name=None,
            pending_input_kind=None,
            last_tool_name=str(pending.get("tool_name") or "connect"),
            last_tool_state="completed",
            last_error=None,
            last_message=str(output.get("message") or ""),
        )
        session.touch()
        return JSONResponse(
            {
                "id": tool_id,
                "name": str(pending.get("tool_name") or "connect"),
                "output": output,
                "success": True,
                "state": "output-available",
                "assistantId": assistant_id,
                "shouldContinue": can_continue,
                "phase": session.phase,
                "deployState": session.deploy_state,
            }
        )

    @app.post("/api/sessions/{session_id}/tools/{tool_id}/input")
    async def submit_tool_input(
        session_id: str,
        tool_id: str,
        request: ToolInputSubmitRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        pending = session.pending_user_input_requests.pop(tool_id, None)
        if pending is None:
            raise HTTPException(status_code=404, detail="未找到待填写的输入请求")

        input_request = pending.get("request")
        if not isinstance(input_request, dict):
            raise HTTPException(status_code=400, detail="当前输入请求结构无效")

        assistant_id = str(pending.get("assistant_id") or "").strip()
        tool_name = str(pending.get("tool_name") or "ask_plan_questions")
        title = str(input_request.get("title") or tool_name).strip()
        answers = _normalize_tool_input_answers(input_request, request)
        output = {
            "message": "已收到用户回答，可以继续完善计划。",
            "kind": str(input_request.get("kind") or pending.get("kind") or "plan_questions"),
            "title": title,
            "answers": answers,
        }
        tool_record = {
            "id": tool_id,
            "name": tool_name,
            "output": output,
            "success": True,
            "state": "output-available",
            "inputRequest": input_request,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        if assistant_id:
            update_assistant_tool_call(
                session,
                assistant_id,
                tool_id,
                lambda existing: {
                    **existing,
                    **tool_record,
                },
            )
        record_tool_result_for_agent(
            session,
            tool_id=tool_id,
            tool_name=tool_name,
            output=output,
            success=True,
            state="output-available",
        )
        record_confirmation_result_for_agent(
            session,
            _format_tool_input_answers_for_agent(title, answers),
        )
        if session.agent_type == "plan":
            deps.set_session_phase(session, "clarifying")
            deps.update_plan_state(session, status="clarifying")
        session.touch()
        return JSONResponse(
            {
                "id": tool_id,
                "name": tool_name,
                "output": output,
                "success": True,
                "state": "output-available",
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
                "phase": session.phase,
                "planState": session.plan_state,
            }
        )
