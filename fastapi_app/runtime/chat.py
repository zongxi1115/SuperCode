from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote_to_bytes

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from agent import AgentEvent
from coding_agent.file_tools import delete_file_in_workspace
from coding_agent.git_tools import execute_git_commit, execute_git_tag
from fastapi_app.app_config import APP_DATA_ROOT
from fastapi_app.api_models import ChatStreamRequest, ContinueChatStreamRequest
from fastapi_app.rag_index import schedule_workspace_rag_index
from fastapi_app.runtime.context import ContextRuntimeDeps
from fastapi_app.code_changes import (
    capture_code_change_before_snapshots,
    code_change_records_from_tool_result,
    current_agent_turn_index,
    ensure_code_change_baseline,
    file_tree_changed_paths_from_tool_result,
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
    seed_chat_session_history,
    stamp_assistant_first_token_latency,
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
from zonix import Agent

STREAM_RESPONSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}

UI_MESSAGE_STREAM_HEADERS = {
    **STREAM_RESPONSE_HEADERS,
    "x-vercel-ai-ui-message-stream": "v1",
}

MAX_CHAT_ATTACHMENTS = 8


class SessionExecutionCancelled(RuntimeError):
    """Raised inside the model event chain to stop the active session run."""


def _data_url_media_type(data_url: str) -> str:
    if not data_url.startswith("data:"):
        return ""
    header = data_url.split(",", 1)[0]
    return header.removeprefix("data:").split(";", 1)[0].strip()


def _decode_attachment_data(data_url: str) -> bytes:
    if data_url.startswith("data:"):
        header, separator, payload = data_url.partition(",")
        if not separator:
            return b""
        if ";base64" in header:
            return base64.b64decode(payload)
        return unquote_to_bytes(payload)
    return base64.b64decode(data_url)


def _safe_upload_filename(filename: str, media_type: str) -> str:
    leaf = Path(filename or "attachment").name.strip() or "attachment"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).strip("._")
    if not safe:
        safe = "attachment"
    if "." not in safe:
        extension = mimetypes.guess_extension(media_type) or ""
        safe = f"{safe}{extension}"
    return safe


def _store_chat_attachments(
    workspace: str | Path,
    session_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    workspace_root = Path(workspace).resolve()
    upload_root = (workspace_root / ".supercode" / "uploads" / session_id).resolve()
    if workspace_root != upload_root and workspace_root not in upload_root.parents:
        raise ValueError("附件保存路径越界。")
    upload_root.mkdir(parents=True, exist_ok=True)

    stored: list[dict[str, Any]] = []
    for attachment in attachments:
        data_url = str(attachment.get("dataUrl") or "").strip()
        if not data_url:
            continue
        try:
            file_bytes = _decode_attachment_data(data_url)
        except Exception:
            continue
        if not file_bytes:
            continue

        media_type = str(attachment.get("mediaType") or "").strip()
        filename = _safe_upload_filename(str(attachment.get("filename") or ""), media_type)
        target = (upload_root / f"{uuid.uuid4().hex[:10]}-{filename}").resolve()
        if upload_root != target.parent and upload_root not in target.parents:
            continue
        target.write_bytes(file_bytes)
        relative_path = str(target.relative_to(workspace_root)).replace("\\", "/")
        item = {
            **attachment,
            "storedPath": relative_path,
            "absolutePath": str(target),
            "size": len(file_bytes),
        }
        if item.get("type") != "image":
            item.pop("dataUrl", None)
        stored.append(item)
    return stored


def _uploaded_files_prompt(attachments: list[dict[str, Any]]) -> str:
    if not attachments:
        return ""
    lines = ["用户上传了文件，已保存到工作区以下路径："]
    for index, attachment in enumerate(attachments, start=1):
        filename = str(attachment.get("filename") or "attachment").strip()
        media_type = str(attachment.get("mediaType") or "application/octet-stream").strip()
        stored_path = str(attachment.get("storedPath") or "").strip()
        size = attachment.get("size")
        size_text = f", {size} bytes" if isinstance(size, int) else ""
        lines.append(f"{index}. {filename} ({media_type}{size_text}): {stored_path}")
    return "\n".join(lines)


def _message_with_uploaded_files(message: str, attachments: list[dict[str, Any]]) -> str:
    prompt = _uploaded_files_prompt(attachments)
    if not prompt:
        return message
    return "\n\n".join(part for part in [message.strip(), prompt] if part)


def _normalize_chat_attachments(request: ChatStreamRequest) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for item in request.attachments[:MAX_CHAT_ATTACHMENTS]:
        data_url = item.dataUrl.strip()
        media_type = item.mediaType.strip()
        if not data_url:
            continue
        if not media_type:
            media_type = _data_url_media_type(data_url)
        attachment_type = "image" if item.type == "image" or media_type.startswith("image/") else "file"
        attachments.append(
            {
                "id": item.id or "",
                "type": attachment_type,
                "filename": item.filename,
                "mediaType": media_type or "application/octet-stream",
                "dataUrl": data_url,
            }
        )
    return attachments


@dataclass(frozen=True)
class ChatRuntimeDeps:
    app_data_root: Path
    session_registry: Any
    normalize_execution_mode: Callable[[str | None], str]
    move_session_to_worktree: Callable[[Any], None]
    normalize_agent_type: Callable[[str | None], str]
    route_session_for_user_message: Callable[..., None]
    update_plan_state: Callable[..., None]
    reset_phase_for_new_turn: Callable[[Any], None]
    sync_session_runtime_state_for_agent: Callable[[Any], None]
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
    attachments: list[dict[str, Any]] | None = None,
    super_autopilot: bool = False,
) -> None:
    loop = asyncio.get_running_loop()
    assistant_id = assistant_id or uuid.uuid4().hex
    streamed_assistant_text = ""
    assistant_stream_started = False
    assistant_turn_index: int | None = None
    tool_before_snapshots: dict[str, dict[str, str]] = {}
    deps.reset_phase_for_new_turn(session)
    deps.sync_session_runtime_state_for_agent(session)
    super_autopilot_enabled = bool(super_autopilot and getattr(session, "agent_type", "") == "super")
    if session.chat_session is not None:
        state = getattr(session.chat_session, "state", None)
        state_data = getattr(state, "data", None)
        if isinstance(state_data, dict):
            runtime_state = state_data.get("runtime_state")
            if not isinstance(runtime_state, dict):
                runtime_state = {}
                state_data["runtime_state"] = runtime_state
            runtime_state["super_autopilot"] = super_autopilot_enabled
            state_data["super_autopilot"] = super_autopilot_enabled
    if user_message is not None:
        visible_user_message = history_user_message if history_user_message is not None else user_message
        ensure_user_message_recorded(
            session,
            visible_user_message,
            attachments=attachments,
        )
    deps.session_registry.set_session_generating(session, True)

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

    def _stamp_assistant_turn_index() -> int | None:
        nonlocal assistant_turn_index
        turn_index = current_agent_turn_index(session)
        if turn_index is None:
            return None
        if assistant_turn_index == turn_index:
            return turn_index
        assistant_turn_index = turn_index
        update_assistant_history_message(
            session,
            assistant_id,
            lambda message: {**message, "turnIndex": turn_index},
        )
        return turn_index

    def _tool_record_with_runtime_metadata(record: dict[str, Any]) -> dict[str, Any]:
        turn_index = _stamp_assistant_turn_index()
        payload = {
            **record,
            "assistantId": assistant_id,
        }
        if turn_index is not None:
            payload["turnIndex"] = turn_index
        return payload

    def _latest_assistant_tool_call() -> dict[str, Any] | None:
        for message in reversed(session.history_messages):
            if not isinstance(message, dict) or str(message.get("id") or "") != assistant_id:
                continue
            tool_calls = message.get("toolCalls")
            if isinstance(tool_calls, list):
                for tool_call in reversed(tool_calls):
                    if isinstance(tool_call, dict) and str(tool_call.get("id") or "").strip():
                        return tool_call
            parts = message.get("parts")
            if not isinstance(parts, list):
                return None
            for part in reversed(parts):
                if not isinstance(part, dict) or part.get("type") != "tool_call":
                    continue
                tool_call = part.get("toolCall")
                if isinstance(tool_call, dict) and str(tool_call.get("id") or "").strip():
                    return tool_call
            return None
        return None

    def _mark_latest_tool_failed(error: str) -> None:
        tool_call = _latest_assistant_tool_call()
        if tool_call is None:
            return
        tool_id = str(tool_call.get("id") or "").strip()
        tool_name = str(tool_call.get("name") or "").strip()
        if not tool_id or not tool_name:
            return
        existing_state = str(tool_call.get("state") or "").strip()
        if existing_state and existing_state not in {"running", "input-requested"}:
            return
        if tool_call.get("success") is not None:
            return
        arguments = tool_call.get("arguments")
        tool_record = _tool_record_with_runtime_metadata(
            {
                "id": tool_id,
                "stepIndex": tool_call.get("stepIndex", tool_call.get("step_index")),
                "name": tool_name,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "output": None,
                "success": False,
                "errorMessage": error,
                "state": "error",
            }
        )
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

    subagent_metadata_by_id: dict[str, dict[str, Any]] = {}

    def _scope_subagent_tool_id(subagent_id: str, tool_id: str) -> str:
        normalized_tool_id = tool_id.strip()
        if not normalized_tool_id:
            return ""
        prefix = f"{subagent_id}:"
        return normalized_tool_id if normalized_tool_id.startswith(prefix) else f"{prefix}{normalized_tool_id}"

    def _normalize_subagent_tool_call_payload(
        subagent_id: str,
        raw_tool_call: object,
    ) -> dict[str, Any] | None:
        if not isinstance(raw_tool_call, dict):
            return None
        tool_call = {**raw_tool_call}
        tool_id = _scope_subagent_tool_id(subagent_id, str(tool_call.get("id") or ""))
        if tool_id:
            tool_call["id"] = tool_id
        return tool_call

    def _normalize_subagent_tool_result_payload(
        subagent_id: str,
        raw_tool_result: object,
    ) -> dict[str, Any] | None:
        if not isinstance(raw_tool_result, dict):
            return None
        tool_result = {**raw_tool_result}
        tool_call_id = _scope_subagent_tool_id(
            subagent_id,
            str(tool_result.get("tool_call_id", tool_result.get("toolCallId")) or ""),
        )
        if tool_call_id:
            tool_result["tool_call_id"] = tool_call_id
            tool_result["toolCallId"] = tool_call_id
        return tool_result

    def _normalize_subagent_event(raw_payload: object) -> dict[str, Any] | None:
        if not isinstance(raw_payload, dict):
            return None
        subagent_id = str(raw_payload.get("subagent_id", raw_payload.get("subagentId")) or "").strip()
        if not subagent_id:
            return None
        event_name = str(raw_payload.get("event") or raw_payload.get("type") or "").strip()
        message_id = str(
            raw_payload.get("message_id", raw_payload.get("messageId"))
            or f"subagent-message-{subagent_id}"
        ).strip()
        parent_tool_call_id = str(
            raw_payload.get("parent_tool_call_id", raw_payload.get("parentToolCallId"))
            or ""
        ).strip()
        parent_assistant_id = str(
            raw_payload.get("parent_assistant_id", raw_payload.get("parentAssistantId"))
            or assistant_id
            or ""
        ).strip()
        final_answer = raw_payload.get("final_answer", raw_payload.get("finalAnswer"))
        if final_answer is None:
            final_answer = raw_payload.get("final_output", raw_payload.get("finalOutput"))
        tool_call = _normalize_subagent_tool_call_payload(
            subagent_id,
            raw_payload.get("tool_call", raw_payload.get("toolCall")),
        )
        tool_result = _normalize_subagent_tool_result_payload(
            subagent_id,
            raw_payload.get("tool_result", raw_payload.get("toolResult")),
        )
        return {
            "event": event_name,
            "messageId": message_id,
            "subagentId": subagent_id,
            "title": str(raw_payload.get("title") or raw_payload.get("subagentTitle") or "子智能体"),
            "agentType": str(raw_payload.get("agent_type", raw_payload.get("agentType")) or "subagent"),
            "task": str(raw_payload.get("task") or raw_payload.get("subagentTask") or ""),
            "parentToolCallId": parent_tool_call_id or None,
            "parentAssistantId": parent_assistant_id or None,
            "stepIndex": raw_payload.get("step_index", raw_payload.get("stepIndex")),
            "message": str(raw_payload.get("message") or ""),
            "delta": raw_payload.get("delta"),
            "thought": raw_payload.get("thought"),
            "finalAnswer": final_answer,
            "usage": raw_payload.get("usage") if isinstance(raw_payload.get("usage"), dict) else None,
            "toolCall": tool_call,
            "toolResult": tool_result,
            "status": raw_payload.get("status"),
            "error": raw_payload.get("error"),
        }

    def _subagent_history_metadata(event_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "agentScope": "subagent",
            "subagentId": event_payload["subagentId"],
            "parentToolCallId": event_payload.get("parentToolCallId"),
            "parentAssistantId": event_payload.get("parentAssistantId"),
            "subagentTitle": event_payload.get("title") or "子智能体",
            "subagentTask": event_payload.get("task") or "",
        }

    def _sync_subagent_message(
        event_payload: dict[str, Any],
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        metadata = _subagent_history_metadata(event_payload)
        message_id = str(event_payload["messageId"])

        def _updater(message: dict[str, Any]) -> dict[str, Any]:
            return sync_assistant_message_fields(updater({**message, **metadata}))

        update_assistant_history_message(session, message_id, _updater)

    def _append_subagent_part_delta(event_payload: dict[str, Any], part_type: str, delta: str) -> None:
        if not delta:
            return

        def _updater(message: dict[str, Any]) -> dict[str, Any]:
            parts = list(message.get("parts") or [])
            last_part = parts[-1] if parts else None
            if isinstance(last_part, dict) and last_part.get("type") == part_type:
                parts[-1] = {**last_part, "text": f"{str(last_part.get('text') or '')}{delta}"}
            else:
                parts.append({"type": part_type, "text": delta})
            return {**message, "parts": parts}

        _sync_subagent_message(event_payload, _updater)

    def _replace_subagent_text(event_payload: dict[str, Any], text: str) -> None:
        def _updater(message: dict[str, Any]) -> dict[str, Any]:
            parts = [
                part
                for part in list(message.get("parts") or [])
                if not (isinstance(part, dict) and part.get("type") == "text")
            ]
            if text:
                parts.append({"type": "text", "text": text})
            return {**message, "parts": parts}

        _sync_subagent_message(event_payload, _updater)

    def _upsert_subagent_data_part(event_payload: dict[str, Any], data_type: str, data: Any) -> None:
        def _updater(message: dict[str, Any]) -> dict[str, Any]:
            parts = list(message.get("parts") or [])
            data_id = str(data.get("id") or "") if isinstance(data, dict) else ""
            replaced = False
            next_parts: list[dict[str, Any]] = []
            for part in parts:
                if not isinstance(part, dict) or part.get("type") != "data":
                    next_parts.append(part)
                    continue
                same_type = str(part.get("dataType") or "") == data_type
                part_data = part.get("data")
                part_data_id = str(part_data.get("id") or "") if isinstance(part_data, dict) else ""
                if same_type and (not data_id or part_data_id == data_id):
                    next_parts.append({"type": "data", "dataType": data_type, "data": data})
                    replaced = True
                else:
                    next_parts.append(part)
            if not replaced:
                next_parts.append({"type": "data", "dataType": data_type, "data": data})
            return {**message, "parts": next_parts}

        _sync_subagent_message(event_payload, _updater)

    def _upsert_subagent_tool_part(event_payload: dict[str, Any], tool_record: dict[str, Any]) -> None:
        tool_id = str(tool_record.get("id") or "").strip()
        if not tool_id:
            return

        def _updater(message: dict[str, Any]) -> dict[str, Any]:
            parts = list(message.get("parts") or [])
            replaced = False
            next_parts: list[dict[str, Any]] = []
            for part in parts:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "tool_call"
                    and isinstance(part.get("toolCall"), dict)
                    and str(part["toolCall"].get("id") or "") == tool_id
                ):
                    next_parts.append({"type": "tool_call", "toolCall": {**part["toolCall"], **tool_record}})
                    replaced = True
                else:
                    next_parts.append(part)
            if not replaced:
                next_parts.append({"type": "tool_call", "toolCall": tool_record})
            next_message = {**message, "parts": next_parts}
            if str(tool_record.get("state") or "") == "running" and tool_record.get("output") is None:
                return stamp_assistant_first_token_latency(next_message)
            return next_message

        _sync_subagent_message(event_payload, _updater)

    def _record_subagent_event(raw_payload: object) -> dict[str, Any] | None:
        event_payload = _normalize_subagent_event(raw_payload)
        if event_payload is None:
            return None

        subagent_metadata_by_id[event_payload["subagentId"]] = event_payload
        event_name = event_payload["event"]
        metadata = _subagent_history_metadata(event_payload)

        if event_name == "assistant_started":
            _sync_subagent_message(event_payload, lambda message: {**message, **metadata})
            return event_payload

        if event_name == "thought_delta":
            _append_subagent_part_delta(event_payload, "thinking", str(event_payload.get("delta") or ""))
            return event_payload

        if event_name == "thought":
            thought_text = str(event_payload.get("thought") or "")
            if thought_text.strip():
                upsert_assistant_thinking_part(session, str(event_payload["messageId"]), thought_text)
                _sync_subagent_message(event_payload, lambda message: message)
            return event_payload

        if event_name == "final_answer_delta":
            _append_subagent_part_delta(event_payload, "text", str(event_payload.get("delta") or ""))
            return event_payload

        if event_name in {"final", "turn_finished", "limit_reached", "assistant_done"}:
            final_output = str(event_payload.get("finalAnswer") or "")
            if final_output:
                _replace_subagent_text(event_payload, final_output)
            return event_payload

        if event_name == "error":
            error_text = str(event_payload.get("error") or event_payload.get("message") or "").strip()
            if error_text:
                _append_subagent_part_delta(event_payload, "text", f"子智能体执行失败：{error_text}")
            return event_payload

        if event_name == "usage":
            deps.merge_session_token_usage(session, event_payload.get("usage"))
            usage = event_payload.get("usage")
            if isinstance(usage, dict):
                _sync_subagent_message(
                    event_payload,
                    lambda message: {**message, "tokenUsage": usage},
                )
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
            return event_payload

        if event_name == "tool_call":
            raw_tool_call = event_payload.get("toolCall")
            if not isinstance(raw_tool_call, dict):
                return event_payload
            tool_id = str(raw_tool_call.get("id") or "").strip()
            tool_name = str(raw_tool_call.get("name") or "").strip()
            if not tool_id or not tool_name:
                return event_payload
            arguments = raw_tool_call.get("arguments")
            tool_record = {
                **metadata,
                "id": tool_id,
                "stepIndex": event_payload.get("stepIndex"),
                "name": tool_name,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "state": "running",
            }
            _upsert_subagent_tool_part(event_payload, tool_record)
            return event_payload

        if event_name == "tool_result":
            raw_tool_call = event_payload.get("toolCall")
            raw_tool_result = event_payload.get("toolResult")
            if not isinstance(raw_tool_result, dict):
                return event_payload
            tool_id = str(
                (raw_tool_call or {}).get("id")
                if isinstance(raw_tool_call, dict)
                else ""
            ).strip() or str(raw_tool_result.get("tool_call_id", raw_tool_result.get("toolCallId")) or "").strip()
            tool_name = str(
                (raw_tool_call or {}).get("name")
                if isinstance(raw_tool_call, dict)
                else ""
            ).strip() or str(raw_tool_result.get("name") or "").strip()
            if not tool_id or not tool_name:
                return event_payload
            arguments = raw_tool_call.get("arguments") if isinstance(raw_tool_call, dict) else {}
            success = raw_tool_result.get("success")
            is_success = success if isinstance(success, bool) else None
            tool_state = "completed" if is_success is not False else "error"
            tool_record = {
                **metadata,
                "id": tool_id,
                "stepIndex": event_payload.get("stepIndex"),
                "name": tool_name,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "output": raw_tool_result.get("output"),
                "success": is_success,
                "errorMessage": raw_tool_result.get("error_message", raw_tool_result.get("errorMessage")),
                "state": tool_state,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            _upsert_subagent_tool_part(event_payload, tool_record)
            session.touch()
            return event_payload

        return event_payload

    def _record_subagent_snapshot(raw_payload: object) -> dict[str, Any] | None:
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        snapshot = payload.get("data", payload)
        if not isinstance(snapshot, dict):
            return None
        subagent_id = str(snapshot.get("id") or "").strip()
        if not subagent_id:
            return None
        base_event = subagent_metadata_by_id.get(subagent_id) or {
            "event": "snapshot",
            "messageId": str(snapshot.get("messageId") or f"subagent-message-{subagent_id}"),
            "subagentId": subagent_id,
            "title": str(snapshot.get("title") or "子智能体"),
            "agentType": str(snapshot.get("agentType") or "subagent"),
            "task": str(snapshot.get("task") or ""),
            "parentToolCallId": None,
            "parentAssistantId": assistant_id,
        }
        _upsert_subagent_data_part(base_event, "data-subagent-task", snapshot)
        return snapshot

    def emit_tool_runtime_event(event_type: str, payload: object) -> None:
        if event_type == "subagent_event":
            def _handle_subagent_event() -> None:
                event_payload = _record_subagent_event(payload)
                if event_payload is None:
                    return
                queue.put_nowait(
                    {
                        "type": "data-subagent-event",
                        "payload": {
                            "assistant_id": assistant_id,
                            "data": event_payload,
                        },
                    }
                )

            loop.call_soon_threadsafe(_handle_subagent_event)
            return

        if event_type == "data-subagent-task":
            def _handle_subagent_snapshot() -> None:
                snapshot = _record_subagent_snapshot(payload)
                data_payload = payload.get("data", payload) if isinstance(payload, dict) else payload
                queue.put_nowait(
                    {
                        "type": "data-subagent-task",
                        "payload": {
                            "assistant_id": assistant_id,
                            "data": data_payload if snapshot is not None else payload,
                        },
                    }
                )

            loop.call_soon_threadsafe(_handle_subagent_snapshot)
            return

        if event_type.startswith("data-"):
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": event_type,
                    "payload": {
                        "assistant_id": assistant_id,
                        "data": payload.get("data", payload) if isinstance(payload, dict) else payload,
                    },
                },
            )

    await queue.put(_session_state_event())
    update_assistant_history_message(session, assistant_id, lambda message: sync_assistant_message_fields(message))

    def on_event(event: AgentEvent) -> None:
        nonlocal streamed_assistant_text, assistant_stream_started

        if session.cancel_event.is_set():
            raise SessionExecutionCancelled("会话已取消")
        _stamp_assistant_turn_index()

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
            update_assistant_history_message(
                session,
                assistant_id,
                lambda message: {**message, "tokenUsage": event.usage},
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "usage",
                    "payload": {
                        "assistant_id": assistant_id,
                        "usage": event.usage,
                    },
                },
            )
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
            elif session.agent_type in {"plan", "super"}:
                tool_name = event.tool_call.name
                if tool_name in {"ask_plan_questions", "ask_user"}:
                    deps.set_session_phase(
                        session,
                        "researching" if session.agent_type == "super" and super_autopilot_enabled else "awaiting_user_input",
                    )
                    if session.agent_type == "plan":
                        deps.update_plan_state(session, status="awaiting_user_input")
                elif tool_name == "save_plan":
                    deps.set_session_phase(session, "planning")
                    if session.agent_type == "plan":
                        deps.update_plan_state(session, status="planning")
                else:
                    deps.set_session_phase(session, "researching")
                    if session.agent_type == "plan":
                        deps.update_plan_state(session, status="researching")
            append_assistant_tool_call(
                session,
                assistant_id,
                _tool_record_with_runtime_metadata(
                    {
                        "id": tool_id,
                        "stepIndex": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                        "state": "running",
                    }
                ),
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
                            ensure_code_change_baseline(session)
                            output = delete_file_in_workspace(filename, resolve_workspace_path(session.workspace))
                            session.mark_file_tree_dirty(paths=[target])
                            file_tree_marked_for_tool_result = True
                            if session.selected_file_path == normalize_relative_path(filename, session.workspace):
                                session.selected_file_path = None
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
            if event.tool_result.name in {
                "execute",
                "run_command",
                "start_task",
                "task_input",
                "task_wait",
                "task_stop",
            } and terminal_output is not None:
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
                    file_tree_marked_for_tool_result = True
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
                input_kind = str(input_request.get("kind") if input_request else "")
                if input_kind == "plan_questions":
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
                if tool_name in {"execute", "run_command"}:
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
                    elif tool_name in {"execute", "run_command"}:
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
            elif (
                requires_user_input
                and isinstance(input_request, dict)
                and str(input_request.get("kind") or "") == "plan_questions"
            ):
                deps.set_session_phase(session, "awaiting_user_input")
            tool_record = _tool_record_with_runtime_metadata(
                {
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
            )
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
                if code_change_records and not file_tree_marked_for_tool_result:
                    changed_paths = [
                        Path(normalize_relative_path(str(record.get("path") or ""), session.workspace))
                        for record in code_change_records
                        if str(record.get("path") or "").strip()
                    ]
                    session.mark_file_tree_dirty(paths=changed_paths or None)
                    file_tree_marked_for_tool_result = True
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

    runtime_agent = getattr(session.chat_session, "agent", None) if session.chat_session is not None else None
    previous_runtime_event_emitter: object = None
    previous_runtime_assistant_id: object = None
    had_runtime_event_emitter = False
    had_runtime_assistant_id = False
    if isinstance(runtime_agent, Agent):
        had_runtime_event_emitter = "runtime_event_emitter" in runtime_agent.tool_context_metadata
        had_runtime_assistant_id = "runtime_assistant_id" in runtime_agent.tool_context_metadata
        previous_runtime_event_emitter = runtime_agent.tool_context_metadata.get("runtime_event_emitter")
        previous_runtime_assistant_id = runtime_agent.tool_context_metadata.get("runtime_assistant_id")
        runtime_agent.tool_context_metadata["runtime_event_emitter"] = emit_tool_runtime_event
        runtime_agent.tool_context_metadata["runtime_assistant_id"] = assistant_id

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
                attachments,
            )
    except SessionExecutionCancelled:
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
        deps.session_registry.set_session_generating(session, False)
        await queue.put(_session_state_event())
        await queue.put(None)
        return
    except Exception as exc:  # noqa: BLE001 - 流式接口需要兜底，避免 SSE 半路中断
        _mark_latest_tool_failed(str(exc))
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
            await asyncio.sleep(0.03)

        persisted_failure_content = (
            f"{streamed_assistant_text}{failure_message}"
            if streamed_assistant_text
            else failure_message.strip()
        )
        replace_assistant_text_part(session, assistant_id, persisted_failure_content.strip())
        if session.chat_session is not None:
            seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        deps.session_registry.set_session_generating(session, False)
        await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
        await queue.put(None)
        return
    finally:
        if isinstance(runtime_agent, Agent):
            if had_runtime_event_emitter:
                runtime_agent.tool_context_metadata["runtime_event_emitter"] = previous_runtime_event_emitter
            else:
                runtime_agent.tool_context_metadata.pop("runtime_event_emitter", None)
            if had_runtime_assistant_id:
                runtime_agent.tool_context_metadata["runtime_assistant_id"] = previous_runtime_assistant_id
            else:
                runtime_agent.tool_context_metadata.pop("runtime_assistant_id", None)

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
        deps.session_registry.set_session_generating(session, False)
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

    if session.chat_session is not None:
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)

    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)
    deps.session_registry.set_session_generating(session, False)


async def _stream_ui_messages(
    queue: asyncio.Queue[dict[str, Any] | None],
    producer: asyncio.Task[None],
    session: Any,
    deps: ChatRuntimeDeps,
):
    adapter = UIMessageStreamAdapter()
    finished = False
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            for part in adapter.convert(event):
                if part.get("type") == "finish":
                    finished = True
                yield sse_data(part)
                if part.get("type") == "tool-input-delta":
                    await asyncio.sleep(0.01)

        if not finished:
            for part in adapter.finish_if_needed():
                yield sse_data(part)
        yield sse_data("[DONE]")
    except asyncio.CancelledError:
        deps.session_registry.stop_session_execution(session)
        raise
    finally:
        if producer.done():
            await producer
        else:
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer


async def run_demo_stream(
    session: Any,
    user_message: str,
    queue: asyncio.Queue[dict[str, Any] | None],
    deps: ChatRuntimeDeps,
) -> None:
    assistant_id = uuid.uuid4().hex
    deps.session_registry.set_session_generating(session, True)
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
        if session.cancel_event.is_set():
            deps.session_registry.set_session_generating(session, False)
            await queue.put(None)
            return
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
    deps.session_registry.set_session_generating(session, False)


def register_chat_routes(
    app: FastAPI,
    *,
    deps: ChatRuntimeDeps,
) -> None:
    @app.post("/api/chat/stream")
    async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
        session = deps.session_registry.require_session(request.session_id)
        session.cancel_event.clear()
        requested_execution_mode = deps.normalize_execution_mode(request.execution_mode)
        if requested_execution_mode == "worktree" and session.execution_mode != "worktree":
            await asyncio.to_thread(deps.move_session_to_worktree, session)
            session.cancel_event.clear()
        original_user_message = request.message.strip()
        raw_attachments = _normalize_chat_attachments(request)
        attachments = _store_chat_attachments(
            session.workspace,
            request.session_id,
            raw_attachments,
        )
        if not original_user_message and not attachments:
            raise HTTPException(status_code=400, detail="message 不能为空")
        base_user_message = (
            original_user_message
            or (
                "用户上传了图片，请结合图片内容回答。"
                if any(item.get("type") == "image" for item in attachments)
                else "用户上传了文件，请结合这些文件路径继续处理。"
            )
        )
        routing_message = _message_with_uploaded_files(base_user_message, attachments)
        user_message, active_skills = resolve_message_skills(
            session.workspace,
            routing_message,
            request.skills,
        )
        if not user_message:
            raise HTTPException(status_code=400, detail="请在选择 skill 后补充具体任务。")
        forced_agent_type = None
        requested_agent_mode = str(request.agent_mode or "").strip().lower()
        if requested_agent_mode and requested_agent_mode != "auto":
            forced_agent_type = deps.normalize_agent_type(requested_agent_mode)
        deps.route_session_for_user_message(session, user_message, forced_agent_type=forced_agent_type)
        super_autopilot_enabled = bool(request.super_autopilot and session.agent_type == "super")
        if session.chat_session is not None:
            session.chat_session.state.data["active_skills"] = active_skills
        if session.agent_type in {"coding", "super"} and session.plan_state.get("pending_coding_input"):
            deps.update_plan_state(session, pending_coding_input=None)

        async def event_generator():
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            user_message_id = uuid.uuid4().hex
            await queue.put(
                {
                    "type": "user_message",
                    "payload": {
                        "id": user_message_id,
                        "content": original_user_message,
                        "attachments": attachments,
                    },
                }
            )
            history_user_record = {
                "id": user_message_id,
                "role": "user",
                "content": original_user_message,
            }
            if attachments:
                history_user_record["attachments"] = attachments
            session.history_messages.append(history_user_record)
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
                    attachments=attachments,
                    super_autopilot=super_autopilot_enabled,
                )
            )

            async for chunk in _stream_ui_messages(queue, producer, session, deps):
                yield chunk

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=UI_MESSAGE_STREAM_HEADERS,
        )

    @app.post("/api/chat/continue")
    async def chat_continue(request: ContinueChatStreamRequest) -> StreamingResponse:
        session = deps.session_registry.require_session(request.session_id)
        if session.chat_session is None:
            raise HTTPException(status_code=409, detail="当前会话不支持 continue")
        session.cancel_event.clear()
        assistant_id = request.assistant_id.strip()
        if not assistant_id:
            raise HTTPException(status_code=400, detail="assistant_id 不能为空")

        async def event_generator():
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            producer = asyncio.create_task(
                run_agent_stream(session, None, queue, deps, assistant_id=assistant_id, resume_existing_turn=True)
            )
            async for chunk in _stream_ui_messages(queue, producer, session, deps):
                yield chunk

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=UI_MESSAGE_STREAM_HEADERS,
        )

