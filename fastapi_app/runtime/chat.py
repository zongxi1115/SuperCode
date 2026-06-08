from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from agent import AgentEvent
from coding_agent.tools import delete_file_in_workspace, execute_git_commit, execute_git_tag
from fastapi_app.app_config import APP_DATA_ROOT
from fastapi_app.api_models import ChatStreamRequest, ContinueChatStreamRequest
from fastapi_app.rag_index import schedule_workspace_rag_index
from fastapi_app.runtime.context import ContextRuntimeDeps
from fastapi_app.code_changes import (
    capture_code_change_before_snapshots,
    code_change_records_from_tool_result,
    current_agent_turn_index,
    file_tree_changed_paths_from_tool_result,
    record_code_change,
)
from fastapi_app.session_history import (
    append_assistant_part_delta,
    append_assistant_tool_call,
    chunk_text,
    clear_assistant_text_part,
    ensure_user_message_recorded,
    extract_preview_url,
    extract_terminal_output,
    finalize_plan_steps,
    record_confirmation_result_for_agent,
    replace_assistant_text_part,
    sync_assistant_message_fields,
    update_assistant_history_message,
    update_assistant_tool_call,
    update_plan_steps_for_tool,
    upsert_assistant_thinking_part,
    upsert_tool,
)
from fastapi_app.settings_store import load_settings
from fastapi_app.skills import resolve_message_skills
from fastapi_app.ui_message_stream import UIMessageStreamAdapter, sse_data
from fastapi_app.workspace_utils import (
    normalize_relative_path,
    pick_demo_file,
    read_text_file,
    render_demo_list_output,
    resolve_workspace_path,
)


@dataclass(frozen=True)
class ChatRuntimeDeps:
    app_data_root: Path
    require_session: Callable[[str], Any]
    normalize_execution_mode: Callable[[str | None], str]
    move_session_to_worktree: Callable[[Any], None]
    normalize_agent_type: Callable[[str | None], str]
    route_session_for_user_message: Callable[..., None]
    update_plan_state: Callable[..., None]
    stop_session_execution: Callable[[Any], Any]
    reset_phase_for_new_turn: Callable[[Any], None]
    sync_session_runtime_state_for_agent: Callable[[Any], None]
    set_session_generating: Callable[[Any, bool], None]
    build_session_state_payload: Callable[[Any], dict[str, Any]]
    merge_session_token_usage: Callable[[Any, dict[str, int] | None], None]
    set_session_phase: Callable[[Any, str], None]
    update_deploy_state: Callable[..., None]
    compact_text: Callable[[str, int], str]
    extract_command_exit_code: Callable[[object], int | None]
    context_runtime_deps: ContextRuntimeDeps
    auto_compress_session_context_if_needed: Callable[..., Any]


async def run_agent_stream(
    session: Any,
    user_message: str | None,
    queue: asyncio.Queue[dict[str, Any] | None],
    deps: ChatRuntimeDeps,
    assistant_id: str | None = None,
    resume_existing_turn: bool = False,
    history_user_message: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    assistant_id = assistant_id or uuid.uuid4().hex
    streamed_assistant_text = ""
    assistant_stream_started = False
    tool_before_snapshots: dict[str, dict[str, str]] = {}
    deps.reset_phase_for_new_turn(session)
    deps.sync_session_runtime_state_for_agent(session)
    if user_message is not None:
        ensure_user_message_recorded(session, history_user_message or user_message)
    deps.set_session_generating(session, True)

    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )

    def _session_state_event() -> dict[str, Any]:
        return {
            "type": "data-session-state",
            "payload": {
                "assistant_id": assistant_id,
                "data": deps.build_session_state_payload(session),
            },
        }

    await queue.put(_session_state_event())
    update_assistant_history_message(session, assistant_id, lambda message: sync_assistant_message_fields(message))

    def on_event(event: AgentEvent) -> None:
        nonlocal streamed_assistant_text, assistant_stream_started

        if session.cancel_event.is_set():
            return

        if event.type == "thought_delta" and event.delta:
            append_assistant_part_delta(session, assistant_id, "thinking", event.delta)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "thought_delta",
                    "payload": {
                        "assistant_id": assistant_id,
                        "delta": event.delta,
                        "thought": event.thought or "",
                    },
                },
            )
            return

        if event.type == "usage":
            deps.merge_session_token_usage(session, event.usage)
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
            return

        if event.type == "thought":
            thought_text = event.thought or ""
            if thought_text:
                session.thoughts.append(thought_text)
                upsert_assistant_thinking_part(session, assistant_id, thought_text)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "thought",
                    "payload": {
                        "assistant_id": assistant_id,
                        "thought": thought_text,
                    },
                },
            )
            return

        if event.type == "final_answer_delta" and event.delta:
            if not assistant_stream_started:
                assistant_stream_started = True
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "assistant_reset", "payload": {"id": assistant_id}},
                )

            streamed_assistant_text += event.delta
            append_assistant_part_delta(session, assistant_id, "text", event.delta)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "assistant_delta",
                    "payload": {
                        "id": assistant_id,
                        "delta": event.delta,
                    },
                },
            )
            return

        if event.type == "tool_call" and event.tool_call is not None:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            before_snapshots = capture_code_change_before_snapshots(
                session,
                tool_name=event.tool_call.name,
                tool_arguments=event.tool_call.arguments,
            )
            if before_snapshots:
                tool_before_snapshots[tool_id] = before_snapshots
            update_plan_steps_for_tool(session, event.step_index, event.tool_call.name)
            if event.tool_call.name == "read_file":
                maybe_filename = event.tool_call.arguments.get("filename")
                maybe_path = maybe_filename if isinstance(maybe_filename, str) else event.tool_call.arguments.get("path")
                if isinstance(maybe_path, str):
                    session.selected_file_path = normalize_relative_path(maybe_path, session.workspace)
            if session.agent_type == "deploy":
                tool_name = event.tool_call.name
                deps.update_deploy_state(
                    session,
                    pending_tool_id=tool_id,
                    pending_tool_name=tool_name,
                    last_tool_name=tool_name,
                    last_tool_state="running",
                    last_error=None,
                )
                if tool_name == "connect":
                    deps.set_session_phase(session, "awaiting_connect_input")
                elif tool_name in {"list_files", "read_file"}:
                    deps.set_session_phase(session, "exploring")
                elif tool_name in {"transfer_files", "execute"}:
                    deps.set_session_phase(session, "executing")
                if tool_name == "transfer_files":
                    deps.update_deploy_state(
                        session,
                        last_command=None,
                        last_command_cwd=str(event.tool_call.arguments.get("target_dir") or "."),
                        last_exit_code=None,
                    )
                elif tool_name == "execute":
                    deps.update_deploy_state(
                        session,
                        last_command=str(event.tool_call.arguments.get("command") or ""),
                        last_command_cwd=str(event.tool_call.arguments.get("cwd") or "."),
                    )
            elif session.agent_type == "plan":
                tool_name = event.tool_call.name
                if tool_name == "ask_plan_questions":
                    deps.set_session_phase(session, "awaiting_user_input")
                    deps.update_plan_state(session, status="awaiting_user_input")
                elif tool_name == "save_plan":
                    deps.set_session_phase(session, "planning")
                    deps.update_plan_state(session, status="planning")
                else:
                    deps.set_session_phase(session, "researching")
                    deps.update_plan_state(session, status="researching")
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": tool_id,
                    "stepIndex": event.step_index,
                    "name": event.tool_call.name,
                    "arguments": event.tool_call.arguments,
                    "state": "running",
                },
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_call",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                        "thought": event.thought or "",
                    },
                },
            )
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "plan_steps",
                    "payload": {
                        "steps": session.plan_steps,
                    },
                },
            )
            return

        if event.type == "tool_input_started" and event.tool_call is not None:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_input_started",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                    },
                },
            )
            return

        if event.type == "tool_input_delta" and event.tool_call is not None and event.delta:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_input_delta",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "delta": event.delta,
                    },
                },
            )
            return

        if event.type == "tool_result" and event.tool_call is not None and event.tool_result is not None:
            tool_id = event.tool_call.id or event.tool_result.tool_call_id or f"step-{event.step_index}-{event.tool_call.name}"
            output = event.tool_result.output
            before_snapshots = tool_before_snapshots.pop(tool_id, None)
            terminal_output = extract_terminal_output(output)
            preview_url = extract_preview_url(output)
            file_tree_marked_for_tool_result = False
            raw_requires_confirmation = bool(
                (event.tool_result.name == "delete_file"
                 or event.tool_result.name == "git_commit"
                 or event.tool_result.name == "git_tag")
                and isinstance(output, dict)
                and output.get("requires_confirmation") is True
            )
            auto_approve_enabled = bool(load_settings(deps.app_data_root).get("autoApprove"))
            if raw_requires_confirmation and auto_approve_enabled:
                approval = {"id": tool_id, "approved": True}
                tool_success = True
                requires_confirmation = False
                if event.tool_result.name == "delete_file" and isinstance(output, dict):
                    filename = str(output.get("filename") or "").strip()
                    if filename:
                        try:
                            target = Path(normalize_relative_path(filename, session.workspace))
                            before_text = read_text_file(str(target), session.workspace)
                            output = delete_file_in_workspace(filename, resolve_workspace_path(session.workspace))
                            session.mark_file_tree_dirty(paths=[target])
                            file_tree_marked_for_tool_result = True
                            if session.selected_file_path == normalize_relative_path(filename, session.workspace):
                                session.selected_file_path = None
                            record_code_change(
                                session,
                                action="deleted",
                                path=target,
                                before_text=before_text,
                                after_text="",
                                source="agent",
                                tool_call_id=tool_id,
                                assistant_id=assistant_id or None,
                                turn_index=current_agent_turn_index(session),
                                step_index=event.step_index,
                            )
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] delete_file 已自动执行：{filename}")
                elif event.tool_result.name == "git_commit" and isinstance(output, dict):
                    commit_message = str(output.get("commit_message") or "").strip()
                    if commit_message:
                        try:
                            output = execute_git_commit(commit_message, resolve_workspace_path(session.workspace))
                            session.mark_file_tree_dirty()
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] git_commit 已自动执行：{commit_message}")
                elif event.tool_result.name == "git_tag" and isinstance(output, dict):
                    tag_name = str(output.get("tag") or "").strip()
                    tag_message = str(output.get("tag_message") or f"Release {tag_name}")
                    if tag_name:
                        try:
                            output = execute_git_tag(tag_name, tag_message, resolve_workspace_path(session.workspace))
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] git_tag 已自动执行：{tag_name}")
            else:
                requires_confirmation = raw_requires_confirmation
                approval = {"id": tool_id} if requires_confirmation else None
                tool_success = None if requires_confirmation else event.tool_result.success
            requires_user_input = bool(
                isinstance(output, dict)
                and output.get("requires_user_input") is True
            )
            if event.tool_result.name in {"execute", "excecute", "terminal_input", "terminal_wait"} and terminal_output is not None:
                session.terminal_output = terminal_output
            if event.tool_result.name in {"write_file", "replace_file", "apply_patch", "generate_image"} or (
                event.tool_result.name == "delete_file" and not requires_confirmation
            ):
                schedule_workspace_rag_index(APP_DATA_ROOT, session.workspace)
                if not file_tree_marked_for_tool_result:
                    changed_paths = file_tree_changed_paths_from_tool_result(
                        session,
                        tool_name=event.tool_result.name,
                        tool_arguments=event.tool_call.arguments,
                        output=output,
                    )
                    session.mark_file_tree_dirty(paths=changed_paths or None)
            if event.tool_result.name == "open_browser" and preview_url is not None:
                session.preview_url = preview_url
            tool_state = (
                "approval-requested"
                if requires_confirmation
                else "input-requested"
                if requires_user_input
                else ("completed" if event.tool_result.success else "error")
            )
            input_request = None
            if requires_confirmation and isinstance(output, dict):
                if event.tool_result.name == "delete_file":
                    session.pending_delete_confirmations[tool_id] = {
                        "filename": str(output.get("filename") or ""),
                        "assistant_id": assistant_id,
                        "step_index": event.step_index,
                    }
                elif event.tool_result.name == "git_commit":
                    session.pending_commit_confirmations[tool_id] = {
                        "commit_message": str(output.get("commit_message") or ""),
                        "assistant_id": assistant_id,
                    }
                elif event.tool_result.name == "git_tag":
                    session.pending_tag_confirmations[tool_id] = {
                        "tag": str(output.get("tag") or ""),
                        "tag_message": str(output.get("tag_message") or ""),
                        "assistant_id": assistant_id,
                    }
            elif requires_user_input and isinstance(output, dict):
                input_request = {
                    "id": tool_id,
                    "kind": str(output.get("input_kind") or event.tool_result.name),
                    "title": str(output.get("title") or ""),
                    "message": str(output.get("message") or ""),
                    "fields": output.get("fields") if isinstance(output.get("fields"), list) else [],
                    "questions": output.get("questions") if isinstance(output.get("questions"), list) else [],
                }
                pending_payload = {
                    "assistant_id": assistant_id,
                    "tool_name": event.tool_result.name,
                    "request": input_request,
                }
                if session.agent_type == "plan":
                    session.pending_user_input_requests[tool_id] = pending_payload
                else:
                    session.pending_connect_requests[tool_id] = pending_payload
            if session.agent_type == "deploy":
                tool_name = event.tool_result.name
                exit_code = deps.extract_command_exit_code(output)
                deploy_updates: dict[str, Any] = {
                    "last_tool_name": tool_name,
                    "last_tool_state": tool_state,
                    "last_message": (
                        str(output.get("message") or "").strip()
                        if isinstance(output, dict)
                        else deps.compact_text(str(output), 200)
                    )
                    or None,
                }
                if tool_name == "execute":
                    deploy_updates["last_exit_code"] = exit_code
                    if exit_code is not None and exit_code != 0:
                        deploy_updates["last_error"] = f"命令退出码为 {exit_code}"
                elif tool_name == "transfer_files":
                    deploy_updates["last_exit_code"] = None
                if requires_user_input:
                    deps.set_session_phase(session, "awaiting_connect_input")
                    deploy_updates.update(
                        {
                            "pending_tool_id": tool_id,
                            "pending_tool_name": tool_name,
                            "pending_input_kind": str(input_request.get("kind") if input_request else ""),
                        }
                    )
                else:
                    deploy_updates.update(
                        {
                            "pending_tool_id": None,
                            "pending_tool_name": None,
                            "pending_input_kind": None,
                        }
                    )
                    if not event.tool_result.success:
                        deps.set_session_phase(session, "failed")
                        deploy_updates["last_error"] = event.tool_result.error_message
                    elif tool_name in {"list_files", "read_file"}:
                        deps.set_session_phase(session, "exploring")
                    elif tool_name == "transfer_files":
                        deps.set_session_phase(session, "connected")
                    elif tool_name == "execute":
                        deps.set_session_phase(session, "failed" if exit_code not in (None, 0) else "verifying")
                    elif tool_name == "connect":
                        deps.set_session_phase(session, "connected")
                deps.update_deploy_state(session, **deploy_updates)
            elif session.agent_type == "plan":
                tool_name = event.tool_result.name
                if requires_user_input:
                    deps.set_session_phase(session, "awaiting_user_input")
                    deps.update_plan_state(session, status="awaiting_user_input")
                elif not event.tool_result.success:
                    deps.set_session_phase(session, "planning")
                    deps.update_plan_state(session, status="clarifying")
                elif tool_name == "save_plan" and isinstance(output, dict) and isinstance(output.get("plan"), dict):
                    deps.set_session_phase(session, "plan_ready")
                    deps.update_plan_state(
                        session,
                        draft=output.get("plan"),
                        status="draft_ready",
                    )
                elif tool_name in {"search_web", "fetch_url_content", "list_file", "grep_file", "read_file"}:
                    deps.set_session_phase(session, "researching")
                    deps.update_plan_state(session, status="researching")
                else:
                    deps.set_session_phase(session, "planning")
                    deps.update_plan_state(session, status="clarifying")
            tool_record = {
                "id": tool_id,
                "stepIndex": event.step_index,
                "name": event.tool_call.name,
                "arguments": event.tool_call.arguments,
                "output": output,
                "success": tool_success,
                "errorMessage": event.tool_result.error_message,
                "state": tool_state,
                "approval": approval,
                "inputRequest": input_request,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            update_assistant_tool_call(
                session,
                assistant_id,
                tool_id,
                lambda existing: {
                    **existing,
                    **tool_record,
                },
            )
            if event.tool_result.success and not requires_confirmation and not requires_user_input:
                code_change_records = code_change_records_from_tool_result(
                    session,
                    tool_name=event.tool_result.name,
                    tool_arguments=event.tool_call.arguments,
                    output=output,
                    tool_call_id=tool_id,
                    assistant_id=assistant_id,
                    step_index=event.step_index,
                    before_snapshots=before_snapshots,
                )
                for record in code_change_records:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "data-code-change",
                            "payload": {
                                "assistant_id": assistant_id,
                                "data": record,
                            },
                        },
                    )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_result",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                        "output": output,
                        "success": tool_success,
                        "error_message": event.tool_result.error_message,
                        "terminal_output": terminal_output,
                        "preview_url": preview_url,
                        "state": tool_state,
                        "approval": approval,
                        "input_request": input_request,
                    },
                },
            )
            if event.tool_result.name in {"create_task", "finish_task", "get_task_status"}:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "plan_steps",
                        "payload": {
                            "steps": session.plan_steps,
                        },
                    },
                )
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
            return

        if event.type in {"final", "turn_finished", "limit_reached"}:
            if session.agent_type == "deploy" and not session.pending_connect_requests and session.phase != "failed":
                deps.set_session_phase(session, "completed")
                deps.update_deploy_state(
                    session,
                    pending_tool_id=None,
                    pending_tool_name=None,
                    pending_input_kind=None,
                )
            if session.agent_type == "plan" and not session.pending_user_input_requests and session.plan_state.get("draft"):
                deps.set_session_phase(session, "plan_ready")
                deps.update_plan_state(session, status="draft_ready")
            finalize_plan_steps(session)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "plan_steps",
                    "payload": {
                        "steps": session.plan_steps,
                    },
                },
            )
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())

    try:
        if resume_existing_turn:
            response = await asyncio.to_thread(
                session.chat_session.continue_turn,
                on_event,
            )
        else:
            if user_message is None:
                raise RuntimeError("续跑前缺少用户消息。")
            response = await asyncio.to_thread(
                session.chat_session.ask,
                user_message,
                on_event,
            )
    except Exception as exc:  # noqa: BLE001 - 流式接口需要兜底，避免 SSE 半路中断
        if session.agent_type == "deploy":
            deps.set_session_phase(session, "failed")
            deps.update_deploy_state(
                session,
                pending_tool_id=None,
                pending_tool_name=None,
                pending_input_kind=None,
                last_tool_state="error",
                last_error=str(exc),
                last_message=str(exc),
            )
        elif session.agent_type == "plan":
            deps.set_session_phase(session, "planning")
            deps.update_plan_state(session, status="clarifying")
        await queue.put(_session_state_event())
        finalize_plan_steps(session)
        await queue.put(
            {
                "type": "plan_steps",
                "payload": {
                    "steps": session.plan_steps,
                },
            }
        )

        failure_message = (
            f"\n\n后端处理在流式阶段失败：{exc}"
            if assistant_stream_started
            else f"后端处理失败：{exc}"
        )
        if not assistant_stream_started:
            await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})

        for chunk in chunk_text(failure_message):
            if not chunk:
                continue
            await queue.put(
                {
                    "type": "assistant_delta",
                    "payload": {
                        "id": assistant_id,
                        "delta": chunk,
                    },
                }
            )

        persisted_failure_content = (
            f"{streamed_assistant_text}{failure_message}"
            if streamed_assistant_text
            else failure_message.strip()
        )
        replace_assistant_text_part(session, assistant_id, persisted_failure_content.strip())
        deps.set_session_generating(session, False)
        await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
        await queue.put(None)
        return

    if session.cancel_event.is_set():
        if session.agent_type == "deploy":
            deps.reset_phase_for_new_turn(session)
            deps.update_deploy_state(
                session,
                pending_tool_id=None,
                pending_tool_name=None,
                pending_input_kind=None,
                last_message="用户已停止当前任务。",
            )
        elif session.agent_type == "plan":
            deps.reset_phase_for_new_turn(session)
        deps.set_session_generating(session, False)
        await queue.put(_session_state_event())
        await queue.put(None)
        return

    if session.agent_type == "deploy" and not session.pending_connect_requests and session.phase != "failed":
        deps.set_session_phase(session, "completed")
        deps.update_deploy_state(
            session,
            pending_tool_id=None,
            pending_tool_name=None,
            pending_input_kind=None,
        )
    if session.agent_type == "plan" and not session.pending_user_input_requests and session.plan_state.get("draft"):
        deps.set_session_phase(session, "plan_ready")
        deps.update_plan_state(session, status="draft_ready")
    await queue.put(_session_state_event())
    final_output = response.final_output
    has_final_output = bool(final_output)
    if has_final_output:
        replace_assistant_text_part(session, assistant_id, final_output)
    remaining_output = final_output
    should_reset_before_replay = not assistant_stream_started
    if assistant_stream_started:
        if not has_final_output:
            remaining_output = ""
            should_reset_before_replay = False
        elif final_output.startswith(streamed_assistant_text):
            remaining_output = final_output[len(streamed_assistant_text) :]
        else:
            should_reset_before_replay = True
            remaining_output = final_output

    if should_reset_before_replay:
        clear_assistant_text_part(session, assistant_id)
        await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})

    for chunk in chunk_text(remaining_output):
        if not chunk:
            continue
        await queue.put(
            {
                "type": "assistant_delta",
                "payload": {
                    "id": assistant_id,
                    "delta": chunk,
                },
            }
        )
        await asyncio.sleep(0.03)

    auto_compression_response = await asyncio.to_thread(
        deps.auto_compress_session_context_if_needed,
        session,
        deps=deps.context_runtime_deps,
    )
    if auto_compression_response is not None:
        await queue.put(_session_state_event())

    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)
    deps.set_session_generating(session, False)


async def run_demo_stream(
    session: Any,
    user_message: str,
    queue: asyncio.Queue[dict[str, Any] | None],
    deps: ChatRuntimeDeps,
) -> None:
    assistant_id = uuid.uuid4().hex
    deps.set_session_generating(session, True)
    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )
    await queue.put(
        {
            "type": "data-session-state",
            "payload": {
                "assistant_id": assistant_id,
                "data": {
                    "agentType": session.agent_type,
                    "phase": session.phase,
                    "deployState": session.deploy_state,
                    "planState": session.plan_state,
                },
            },
        }
    )
    update_assistant_history_message(session, assistant_id, lambda message: sync_assistant_message_fields(message))
    demo_file = pick_demo_file(session.workspace)
    demo_events = [
        ("thought", {"thought": f"先分析当前工作区 {session.workspace}，确认目录结构和可操作文件。"}),
        (
            "tool_call",
            {
                "id": "step-1-list_file",
                "step_index": 1,
                "name": "list_file",
                "arguments": {"path": "."},
                "thought": "先看当前工作区顶层结构，确认接下来要读哪些文件。",
            },
        ),
        (
            "tool_result",
            {
                "id": "step-1-list_file",
                "step_index": 1,
                "name": "list_file",
                "arguments": {"path": "."},
                "output": render_demo_list_output(session.workspace),
                "success": True,
                "error_message": None,
            },
        ),
        ("thought", {"thought": "接着挑一个代表性文件读一下，验证文件预览和工具链是否同步。"}),
        (
            "tool_call",
            {
                "id": "step-2-read_file",
                "step_index": 2,
                "name": "read_file",
                "arguments": {"filename": demo_file or "", "start_line": 1, "end_line": 120},
                "thought": "读取示例文件，确认当前工作区里的代码内容能回显到右侧预览区。",
            },
        ),
        (
            "tool_result",
            {
                "id": "step-2-read_file",
                "step_index": 2,
                "name": "read_file",
                "arguments": {"filename": demo_file or "", "start_line": 1, "end_line": 120},
                "output": read_text_file(demo_file, session.workspace) if demo_file else "当前工作区里暂时没有合适的文本文件可预览。",
                "success": bool(demo_file),
                "error_message": None if demo_file else "未找到可预览文件",
            },
        ),
    ]

    for event_type, payload in demo_events:
        if event_type == "thought":
            thought_text = str(payload["thought"])
            session.thoughts.append(thought_text)
            upsert_assistant_thinking_part(session, assistant_id, thought_text)
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        elif event_type == "tool_call":
            update_plan_steps_for_tool(
                session,
                payload.get("step_index"),
                str(payload.get("name", "")),
            )
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "state": "running",
                },
            )
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        else:
            session.history_tools = upsert_tool(
                session.history_tools,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "output": payload.get("output"),
                    "success": payload.get("success"),
                    "errorMessage": payload.get("error_message"),
                    "state": "completed" if payload.get("success", True) else "error",
                    "thought": payload.get("thought"),
                },
            )
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "output": payload.get("output"),
                    "success": payload.get("success"),
                    "errorMessage": payload.get("error_message"),
                    "state": "completed" if payload.get("success", True) else "error",
                },
            )
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        await queue.put({"type": event_type, "payload": payload})
        if event_type == "tool_call":
            await queue.put({"type": "plan_steps", "payload": {"steps": session.plan_steps}})
        await asyncio.sleep(0.18)

    answer = (
        f"已收到你的请求：{user_message}\n\n"
        "当前雏形会优先把聊天消息、思考步骤、工具调用链、文件树和终端输出全部打通。"
        "如果检测到真实模型配置，就会切到现有 Agent 执行循环；没有配置时则保持 demo 流，方便你先联调前端。"
    )
    replace_assistant_text_part(session, assistant_id, answer)
    await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})
    for chunk in chunk_text(answer):
        await queue.put({"type": "assistant_delta", "payload": {"id": assistant_id, "delta": chunk}})
        await asyncio.sleep(0.03)

    finalize_plan_steps(session)
    await queue.put({"type": "plan_steps", "payload": {"steps": session.plan_steps}})
    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)
    deps.set_session_generating(session, False)


def register_chat_routes(
    app: FastAPI,
    *,
    deps: ChatRuntimeDeps,
) -> None:
    @app.post("/api/chat/stream")
    async def chat_stream(
        request: ChatStreamRequest,
        protocol: str = Query("ui-message"),
    ) -> StreamingResponse:
        session = deps.require_session(request.session_id)
        session.cancel_event.clear()
        requested_execution_mode = deps.normalize_execution_mode(request.execution_mode)
        if requested_execution_mode == "worktree" and session.execution_mode != "worktree":
            await asyncio.to_thread(deps.move_session_to_worktree, session)
            session.cancel_event.clear()
        original_user_message = request.message.strip()
        if not original_user_message:
            raise HTTPException(status_code=400, detail="message 不能为空")
        user_message, active_skills = resolve_message_skills(
            session.workspace,
            original_user_message,
            request.skills,
        )
        if not user_message:
            raise HTTPException(status_code=400, detail="请在选择 skill 后补充具体任务。")
        forced_agent_type = None
        requested_agent_mode = str(request.agent_mode or "").strip().lower()
        if requested_agent_mode and requested_agent_mode != "auto":
            forced_agent_type = deps.normalize_agent_type(requested_agent_mode)
        deps.route_session_for_user_message(session, user_message, forced_agent_type=forced_agent_type)
        if session.chat_session is not None:
            session.chat_session.state.data["active_skills"] = active_skills
        if session.agent_type == "coding" and session.plan_state.get("pending_coding_input"):
            deps.update_plan_state(session, pending_coding_input=None)

        async def event_generator():
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            ui_adapter = UIMessageStreamAdapter()
            ui_finished = False
            user_message_id = uuid.uuid4().hex
            await queue.put(
                {
                    "type": "user_message",
                    "payload": {
                        "id": user_message_id,
                        "content": original_user_message,
                    },
                }
            )
            session.history_messages.append(
                {"id": user_message_id, "role": "user", "content": original_user_message}
            )
            session.touch()

            producer = asyncio.create_task(
                run_demo_stream(session, user_message, queue, deps)
                if session.chat_session is None
                else run_agent_stream(
                    session,
                    user_message,
                    queue,
                    deps,
                    history_user_message=original_user_message,
                )
            )

            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    if protocol == "legacy":
                        yield sse_data(event)
                        continue

                    for part in ui_adapter.convert(event):
                        if part.get("type") == "finish":
                            ui_finished = True
                        yield sse_data(part)
                        if part.get("type") == "tool-input-delta":
                            await asyncio.sleep(0.01)

                if protocol != "legacy" and not ui_finished:
                    for part in ui_adapter.finish_if_needed():
                        yield sse_data(part)
                if protocol != "legacy":
                    yield sse_data("[DONE]")
            except asyncio.CancelledError:
                deps.stop_session_execution(session)
                raise
            finally:
                if producer.done():
                    await producer
                else:
                    producer.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer

        if protocol == "legacy":
            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "x-vercel-ai-ui-message-stream": "v1",
                "Cache-Control": "no-cache",
            },
        )

    @app.post("/api/chat/continue")
    async def chat_continue(
        request: ContinueChatStreamRequest,
        protocol: str = Query("ui-message"),
    ) -> StreamingResponse:
        session = deps.require_session(request.session_id)
        if session.chat_session is None:
            raise HTTPException(status_code=409, detail="当前会话不支持 continue")
        session.cancel_event.clear()
        assistant_id = request.assistant_id.strip()
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id 不能为空")

        async def event_generator():
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            ui_adapter = UIMessageStreamAdapter()
            ui_finished = False

            producer = asyncio.create_task(
                run_agent_stream(session, None, queue, deps, assistant_id=assistant_id, resume_existing_turn=True)
            )

            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    if protocol == "legacy":
                        yield sse_data(event)
                        continue

                    for part in ui_adapter.convert(event):
                        if part.get("type") == "finish":
                            ui_finished = True
                        yield sse_data(part)
                        if part.get("type") == "tool-input-delta":
                            await asyncio.sleep(0.01)

                if protocol != "legacy" and not ui_finished:
                    for part in ui_adapter.finish_if_needed():
                        yield sse_data(part)
                if protocol != "legacy":
                    yield sse_data("[DONE]")
            except asyncio.CancelledError:
                deps.stop_session_execution(session)
                raise
            finally:
                if producer.done():
                    await producer
                else:
                    producer.cancel()
                    with suppress(asyncio.CancelledError):
                        await producer

        if protocol == "legacy":
            return StreamingResponse(event_generator(), media_type="text/event-stream")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "x-vercel-ai-ui-message-stream": "v1",
                "Cache-Control": "no-cache",
            },
        )

