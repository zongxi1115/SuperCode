from __future__ import annotations

import time
import uuid
import json
from typing import Any

from agent import ConversationMessage, StepRecord, ToolCall, ToolResult

MAX_PLANNING_RECORD_CHARS = 1_200
MAX_STORED_TOOL_RECORDS = 80
MAX_ASSISTANT_TRACE_SUMMARY_CHARS = 2_400
MAX_ASSISTANT_TRACE_SUMMARY_TOOLS = 8
SUBAGENT_SCOPE = "subagent"


def is_subagent_record(record: dict[str, Any]) -> bool:
    return str(record.get("agentScope", record.get("agent_scope")) or "").strip() == SUBAGENT_SCOPE


def ensure_user_message_recorded(
    session: Any,
    user_message: str,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    cleaned_message = user_message.strip()
    normalized_attachments = _normalize_history_attachments(attachments)
    if not cleaned_message and not normalized_attachments:
        return
    last_message = session.history_messages[-1] if session.history_messages else None
    if (
        isinstance(last_message, dict)
        and last_message.get("role") == "user"
        and str(last_message.get("content", "")).strip() == cleaned_message
        and _normalize_history_attachments(last_message.get("attachments")) == normalized_attachments
    ):
        return
    message = {"id": uuid.uuid4().hex, "role": "user", "content": cleaned_message}
    if normalized_attachments:
        message["attachments"] = normalized_attachments
    session.history_messages.append(message)
    session.touch()


def _normalize_history_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []
    attachments: list[dict[str, Any]] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("dataUrl") or item.get("data_url") or item.get("url") or "").strip()
        stored_path = str(item.get("storedPath") or item.get("stored_path") or "").strip()
        media_type = str(item.get("mediaType") or item.get("media_type") or "").strip()
        if not data_url and not stored_path:
            continue
        if not media_type and data_url.startswith("data:image/"):
            media_type = data_url.split(";", 1)[0].removeprefix("data:")
        attachment_type = str(item.get("type") or "").strip()
        if attachment_type not in {"image", "file"}:
            attachment_type = "image" if media_type.startswith("image/") else "file"
        normalized = {
            "id": str(item.get("id") or ""),
            "type": attachment_type,
            "filename": str(item.get("filename") or item.get("name") or ""),
            "mediaType": media_type or "application/octet-stream",
        }
        if data_url:
            normalized["dataUrl"] = data_url
        if stored_path:
            normalized["storedPath"] = stored_path
        absolute_path = str(item.get("absolutePath") or item.get("absolute_path") or "").strip()
        if absolute_path:
            normalized["absolutePath"] = absolute_path
        size = item.get("size")
        if isinstance(size, int):
            normalized["size"] = size
        attachments.append(normalized)
    return attachments


def _uploaded_files_prompt_from_history(raw_attachments: Any) -> str:
    attachments = [
        attachment
        for attachment in _normalize_history_attachments(raw_attachments)
        if str(attachment.get("storedPath") or "").strip()
    ]
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


def update_assistant_history_message(
    session: Any,
    assistant_id: str,
    updater: Any,
) -> None:
    current_message = next(
        (
            message
            for message in session.history_messages
            if message.get("id") == assistant_id and message.get("role") == "assistant"
        ),
        None,
    )
    base_message = (
        {**current_message}
        if isinstance(current_message, dict)
        else {
            "id": assistant_id,
            "role": "assistant",
            "content": "",
            "thoughts": "",
            "toolCalls": [],
            "parts": [],
            "startTime": time.time(),  # 记录消息开始时间
        }
    )
    next_message = updater(base_message)
    session.history_messages = upsert_message(session.history_messages, next_message)
    session.touch()


def sync_assistant_message_fields(message: dict[str, Any]) -> dict[str, Any]:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return message

    text_parts = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    thinking_parts = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "thinking" and str(part.get("text") or "").strip()
    ]
    tool_calls = [
        part.get("toolCall")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "tool_call" and isinstance(part.get("toolCall"), dict)
    ]

    # 计算思考时间（仅在有内容时）
    thinking_time = None
    start_time = message.get("startTime")
    if start_time and (text_parts or thinking_parts or tool_calls):
        thinking_time = time.time() - start_time

    result = {
        **message,
        "content": "".join(text_parts),
        "thoughts": "\n\n".join(thinking_parts),
        "toolCalls": tool_calls,
    }

    # 添加思考时间字段
    if thinking_time is not None:
        result["thinkingTime"] = round(thinking_time, 1)

    return result


def append_assistant_part_delta(
    session: Any,
    assistant_id: str,
    part_type: str,
    delta: str,
) -> None:
    if not delta:
        return

    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        last_part = parts[-1] if parts else None
        if isinstance(last_part, dict) and last_part.get("type") == part_type:
            parts[-1] = {**last_part, "text": f"{str(last_part.get('text') or '')}{delta}"}
        else:
            parts.append({"type": part_type, "text": delta})
        next_message = {**message, "parts": parts}
        if part_type == "text" and next_message.get("firstTokenLatencyMs") is None:
            start_time = next_message.get("startTime")
            try:
                start_seconds = float(start_time)
            except (TypeError, ValueError):
                start_seconds = 0.0
            if start_seconds > 0:
                if start_seconds > 1_000_000_000_000:
                    latency_ms = time.time() * 1000 - start_seconds
                else:
                    latency_ms = (time.time() - start_seconds) * 1000
                next_message["firstTokenLatencyMs"] = max(round(latency_ms), 0)
        return sync_assistant_message_fields(next_message)

    update_assistant_history_message(session, assistant_id, _updater)


def upsert_assistant_thinking_part(
    session: Any,
    assistant_id: str,
    thought_text: str,
) -> None:
    if not thought_text.strip():
        return

    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            if not isinstance(part, dict) or part.get("type") != "thinking":
                continue
            existing_text = str(part.get("text") or "")
            if thought_text.startswith(existing_text) or existing_text.startswith(thought_text):
                parts[index] = {**part, "text": thought_text}
                return sync_assistant_message_fields({**message, "parts": parts})
            break
        parts.append({"type": "thinking", "text": thought_text})
        return sync_assistant_message_fields({**message, "parts": parts})

    update_assistant_history_message(session, assistant_id, _updater)


def replace_assistant_text_part(
    session: Any,
    assistant_id: str,
    text: str,
) -> None:
    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = [
            part
            for part in list(message.get("parts") or [])
            if not (isinstance(part, dict) and part.get("type") == "text")
        ]
        if text:
            parts.append({"type": "text", "text": text})
        return sync_assistant_message_fields({**message, "parts": parts})

    update_assistant_history_message(session, assistant_id, _updater)


def clear_assistant_text_part(session: Any, assistant_id: str) -> None:
    replace_assistant_text_part(session, assistant_id, "")


def append_assistant_tool_call(
    session: Any,
    assistant_id: str,
    tool_call: dict[str, Any],
) -> None:
    tool_id = str(tool_call.get("id") or "").strip()
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
                next_parts.append({"type": "tool_call", "toolCall": {**part["toolCall"], **tool_call}})
                replaced = True
            else:
                next_parts.append(part)
        if not replaced:
            next_parts.append({"type": "tool_call", "toolCall": tool_call})
        return sync_assistant_message_fields({**message, "parts": next_parts})

    update_assistant_history_message(session, assistant_id, _updater)


def update_assistant_tool_call(
    session: Any,
    assistant_id: str,
    tool_id: str,
    updater: Any,
) -> None:
    def _message_updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        next_parts: list[dict[str, Any]] = []
        found = False
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") == "tool_call"
                and isinstance(part.get("toolCall"), dict)
                and str(part["toolCall"].get("id") or "") == tool_id
            ):
                next_parts.append({"type": "tool_call", "toolCall": updater({**part["toolCall"]})})
                found = True
            else:
                next_parts.append(part)
        if not found:
            next_parts.append({"type": "tool_call", "toolCall": updater({"id": tool_id})})
        return sync_assistant_message_fields({**message, "parts": next_parts})

    update_assistant_history_message(session, assistant_id, _message_updater)


def _coerce_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _compact_history_value(value: object, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    compact = " ".join(text.split()).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def extract_message_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append(raw_tool_call: object) -> None:
        if not isinstance(raw_tool_call, dict):
            return
        tool_id = str(raw_tool_call.get("id") or "").strip()
        if tool_id and tool_id in seen_ids:
            return
        if tool_id:
            seen_ids.add(tool_id)
        records.append(raw_tool_call)

    raw_tool_calls = message.get("toolCalls")
    if isinstance(raw_tool_calls, list):
        for raw_tool_call in raw_tool_calls:
            append(raw_tool_call)

    raw_parts = message.get("parts")
    if isinstance(raw_parts, list):
        for part in raw_parts:
            if not isinstance(part, dict):
                continue
            append(part.get("toolCall"))

    return records


def build_assistant_tool_trace_summary(message: dict[str, Any]) -> str:
    if is_subagent_record(message):
        return ""
    if str(message.get("role") or "") != "assistant":
        return ""

    tool_calls = extract_message_tool_calls(message)
    thought_text = extract_message_thought_text(message)
    if not tool_calls and not thought_text:
        return ""

    state_counts: dict[str, int] = {}
    for tool_call in tool_calls:
        state = str(tool_call.get("state") or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1

    lines = [
        "[内部工具轨迹摘要] 上一轮助手没有产生完整的可展示最终回复，但以下执行轨迹已经真实发生；继续对话时必须沿用这些结果，不要从头重做。",
    ]
    if tool_calls:
        state_text = ", ".join(
            f"{state}={count}" for state, count in sorted(state_counts.items())
        )
        lines.append(f"- 工具调用数: {len(tool_calls)}" + (f" ({state_text})" if state_text else ""))

        recent_tools = tool_calls[-MAX_ASSISTANT_TRACE_SUMMARY_TOOLS:]
        for index, tool_call in enumerate(recent_tools, start=1):
            name = str(tool_call.get("name") or "unknown")
            state = str(tool_call.get("state") or "unknown")
            success = tool_call.get("success")
            arguments = tool_call.get("arguments")
            error = tool_call.get("errorMessage", tool_call.get("error_message"))
            output = tool_call.get("output")
            summary_bits = [f"{index}. {name}", f"state={state}"]
            if success is not None:
                summary_bits.append(f"success={success}")
            args_text = _compact_history_value(arguments, 180)
            if args_text:
                summary_bits.append(f"args={args_text}")
            error_text = _compact_history_value(error, 180)
            if error_text:
                summary_bits.append(f"error={error_text}")
            elif output is not None:
                output_text = _compact_history_value(output, 180)
                if output_text:
                    summary_bits.append(f"output={output_text}")
            lines.append("- " + " | ".join(summary_bits))
    if thought_text:
        lines.append(f"- 最近思路: {_compact_history_value(thought_text, 260)}")

    summary = "\n".join(lines)
    if len(summary) <= MAX_ASSISTANT_TRACE_SUMMARY_CHARS:
        return summary
    return f"{summary[:MAX_ASSISTANT_TRACE_SUMMARY_CHARS].rstrip()}..."


def model_content_from_history_message(message: dict[str, Any]) -> str:
    role = str(message.get("role", ""))
    content = str(message.get("content", "") or "").strip()
    if role == "user" and not is_subagent_record(message):
        uploaded_files_prompt = _uploaded_files_prompt_from_history(message.get("attachments"))
        if uploaded_files_prompt and "用户上传了文件，已保存到工作区以下路径：" not in content:
            return "\n\n".join(part for part in [content, uploaded_files_prompt] if part)
        return content
    if role != "assistant" or is_subagent_record(message):
        return content

    return content


def build_step_records_from_tool_records(tool_records: list[dict[str, Any]]) -> list[StepRecord]:
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for fallback_index, record in enumerate(tool_records, start=1):
        turn_index = _coerce_optional_int(record.get("turn_index")) or 0
        step_index = _coerce_optional_int(record.get("step_index")) or fallback_index
        group = grouped.setdefault(
            (turn_index, step_index),
            {"thought": "", "tool_calls": [], "tool_results": []},
        )

        thought = str(record.get("thought") or "").strip()
        if thought and not group["thought"]:
            group["thought"] = thought

        name = str(record.get("name") or "").strip()
        if not name:
            continue
        tool_id = str(record.get("id") or "").strip() or None
        arguments = record.get("arguments")
        tool_call = ToolCall(
            name=name,
            id=tool_id,
            arguments=arguments if isinstance(arguments, dict) else {},
        )
        group["tool_calls"].append(tool_call)

        state = str(record.get("state") or "").strip()
        success = record.get("success")
        has_result = (
            success is not None
            or record.get("output") is not None
            or bool(record.get("error_message"))
            or state in {"completed", "error", "output-available", "output-denied"}
        )
        if has_result:
            group["tool_results"].append(
                ToolResult(
                    name=name,
                    output=record.get("output"),
                    tool_call_id=tool_id,
                    success=success if isinstance(success, bool) else state not in {"error", "output-denied"},
                    error_message=(
                        str(record.get("error_message"))
                        if record.get("error_message") is not None
                        else None
                    ),
                )
            )

    step_records: list[StepRecord] = []
    for (turn_index, step_index), group in sorted(grouped.items()):
        tool_calls = group["tool_calls"]
        tool_results = group["tool_results"]
        first_tool_call = tool_calls[0] if tool_calls else None
        first_tool_result = tool_results[0] if tool_results else None
        step_records.append(
            StepRecord(
                turn_index=turn_index,
                index=step_index,
                thought=str(group["thought"]),
                tool_call=first_tool_call,
                tool_result=first_tool_result,
                tool_calls=tool_calls,
                tool_results=tool_results,
            )
        )
    return step_records


def seed_chat_session_history(
    chat_session: Any,
    history_messages: list[dict[str, Any]],
    history_tools: list[dict[str, Any]] | None = None,
) -> None:
    conversation_messages: list[ConversationMessage] = []
    for message in history_messages:
        role = str(message.get("role", ""))
        if role not in {"user", "assistant"} or is_subagent_record(message):
            continue
        content = model_content_from_history_message(message)
        attachments = _normalize_history_attachments(message.get("attachments")) if role == "user" else []
        if not content.strip() and not attachments:
            continue
        conversation_messages.append(
            ConversationMessage(
                role=role,
                content=content,
                reasoning_content=(
                    extract_message_thought_text(message)
                    if role == "assistant"
                    else None
                ) or None,
                attachments=attachments,
            )
        )
    chat_session.state.conversation_messages = conversation_messages
    tool_records = build_tool_records_from_history(history_messages, history_tools or [])
    if tool_records:
        chat_session.state.data["tool_records"] = tool_records
        chat_session.state.data["step_records"] = build_step_records_from_tool_records(tool_records)
    planning_records = build_planning_records_from_history(history_messages)
    if planning_records:
        chat_session.state.data["planning_records"] = planning_records
    chat_session.state.data["turn_index"] = _max_turn_index(
        history_messages,
        tool_records,
        planning_records,
    )


def _max_turn_index(
    history_messages: list[dict[str, Any]],
    tool_records: list[dict[str, Any]],
    planning_records: list[dict[str, Any]],
) -> int:
    values: list[int] = []
    for message in history_messages:
        if not isinstance(message, dict):
            continue
        turn_index = _coerce_optional_int(message.get("turnIndex", message.get("turn_index")))
        if turn_index is not None:
            values.append(turn_index)
    for record in [*tool_records, *planning_records]:
        if not isinstance(record, dict):
            continue
        turn_index = _coerce_optional_int(record.get("turn_index", record.get("turnIndex")))
        if turn_index is not None:
            values.append(turn_index)
    return max(values, default=0)


def record_confirmation_result_for_agent(session: Any, content: str) -> None:
    if session.chat_session is None:
        return
    text = content.strip()
    if not text:
        return
    records = list(session.chat_session.state.data.get("external_records", []))
    records.append(text)
    session.chat_session.state.data["external_records"] = records[-20:]


def record_tool_result_for_agent(
    session: Any,
    *,
    tool_id: str,
    tool_name: str,
    output: Any,
    success: bool = True,
    state: str = "completed",
    error_message: str | None = None,
) -> bool:
    if session.chat_session is None:
        return False

    normalized_tool_id = tool_id.strip()
    if not normalized_tool_id:
        return False

    result = ToolResult(
        name=tool_name,
        output=output,
        tool_call_id=normalized_tool_id,
        success=success,
        error_message=error_message,
    )
    agent_state = session.chat_session.state
    updated_step = _replace_step_tool_result(
        agent_state.data.get("step_records", []),
        normalized_tool_id,
        result,
    )
    _replace_latest_tool_result(agent_state.tool_results, normalized_tool_id, result)
    _upsert_agent_tool_record(
        agent_state.data,
        normalized_tool_id,
        tool_name,
        output,
        success=success,
        state=state,
        error_message=error_message,
        matched_step=updated_step,
    )
    return updated_step is not None


def _replace_step_tool_result(
    step_records: object,
    tool_id: str,
    result: ToolResult,
) -> StepRecord | None:
    if not isinstance(step_records, list):
        return None

    for step in reversed(step_records):
        if not isinstance(step, StepRecord):
            continue
        tool_calls = step.tool_calls or ([step.tool_call] if step.tool_call is not None else [])
        if not any(tool_call is not None and tool_call.id == tool_id for tool_call in tool_calls):
            continue

        tool_results = step.tool_results or ([step.tool_result] if step.tool_result is not None else [])
        next_results: list[ToolResult] = []
        replaced = False
        for existing_result in tool_results:
            if existing_result is not None and existing_result.tool_call_id == tool_id:
                next_results.append(result)
                replaced = True
            elif existing_result is not None:
                next_results.append(existing_result)
        if not replaced:
            next_results.append(result)

        step.tool_results = next_results
        if step.tool_call is not None and step.tool_call.id == tool_id:
            step.tool_result = result
        return step

    return None


def _replace_latest_tool_result(
    tool_results: list[ToolResult],
    tool_id: str,
    result: ToolResult,
) -> None:
    for index, existing_result in enumerate(tool_results):
        if existing_result.tool_call_id == tool_id:
            tool_results[index] = result
            return
    tool_results.append(result)


def _upsert_agent_tool_record(
    state_data: dict[str, Any],
    tool_id: str,
    tool_name: str,
    output: Any,
    *,
    success: bool,
    state: str,
    error_message: str | None,
    matched_step: StepRecord | None,
) -> None:
    records = [
        record
        for record in list(state_data.get("tool_records", []))
        if isinstance(record, dict)
    ]
    next_record: dict[str, Any] = {
        "id": tool_id,
        "name": tool_name,
        "output": output,
        "success": success,
        "state": state,
        "error_message": error_message,
    }
    if matched_step is not None:
        next_record["turn_index"] = matched_step.turn_index
        next_record["step_index"] = matched_step.index
        matching_call = next(
            (
                tool_call
                for tool_call in (matched_step.tool_calls or ([matched_step.tool_call] if matched_step.tool_call is not None else []))
                if tool_call is not None and tool_call.id == tool_id
            ),
            None,
        )
        if matching_call is not None:
            next_record["arguments"] = matching_call.arguments

    for index, record in enumerate(records):
        if str(record.get("id") or "") == tool_id:
            records[index] = {**record, **next_record}
            break
    else:
        records.append(next_record)

    state_data["tool_records"] = records[-MAX_STORED_TOOL_RECORDS:]


def build_tool_records_from_history(
    history_messages: list[dict[str, Any]],
    history_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    record_index_by_id: dict[str, int] = {}

    def upsert(raw_record: dict[str, Any]) -> None:
        normalized = normalize_tool_record(raw_record)
        tool_id = str(normalized.get("id") or "").strip()
        if not tool_id:
            records.append(normalized)
            return
        existing_index = record_index_by_id.get(tool_id)
        if existing_index is None:
            record_index_by_id[tool_id] = len(records)
            records.append(normalized)
            return
        records[existing_index] = {**records[existing_index], **normalized}

    for message_index, message in enumerate(history_messages, start=1):
        if is_subagent_record(message):
            continue
        message_turn = _coerce_optional_int(
            message.get("turnIndex", message.get("turn_index"))
        ) or message_index
        assistant_id = str(message.get("id") or "").strip()
        for raw_tool_call in extract_message_tool_calls(message):
            tool_call = {**raw_tool_call}
            tool_call.setdefault("turnIndex", message_turn)
            if assistant_id:
                tool_call.setdefault("assistantId", assistant_id)
            upsert(tool_call)

    for raw_tool in history_tools:
        if isinstance(raw_tool, dict) and not is_subagent_record(raw_tool):
            upsert(raw_tool)

    return records


def build_planning_records_from_history(history_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for message_index, message in enumerate(history_messages, start=1):
        if is_subagent_record(message):
            continue
        if str(message.get("role", "")) != "assistant":
            continue
        thought_text = extract_message_thought_text(message)
        if not thought_text:
            continue
        records.append(
            {
                "id": str(message.get("id") or f"assistant-{message_index}"),
                "turn_index": message_index,
                "step_index": None,
                "thought": compact_planning_text(thought_text),
                "action": "assistant",
                "tools": [
                    str(tool_call.get("name") or "")
                    for tool_call in message.get("toolCalls", [])
                    if isinstance(tool_call, dict) and str(tool_call.get("name") or "").strip()
                ],
            }
        )
    return records


def extract_message_thought_text(message: dict[str, Any]) -> str:
    direct_thoughts = str(message.get("thoughts") or "").strip()
    if direct_thoughts:
        return direct_thoughts

    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    thinking_parts = [
        str(part.get("text") or "").strip()
        for part in parts
        if isinstance(part, dict) and part.get("type") == "thinking" and str(part.get("text") or "").strip()
    ]
    return "\n\n".join(thinking_parts)


def compact_planning_text(text: str) -> str:
    compact = " ".join(text.split()).strip()
    if len(compact) <= MAX_PLANNING_RECORD_CHARS:
        return compact
    return f"{compact[:MAX_PLANNING_RECORD_CHARS].rstrip()}... [truncated]"


def normalize_tool_record(raw_record: dict[str, Any]) -> dict[str, Any]:
    raw_success = raw_record.get("success")
    success = raw_success if isinstance(raw_success, bool) else None
    state = str(raw_record.get("state") or ("completed" if success is True else "error" if success is False else ""))
    arguments = raw_record.get("arguments")
    normalized = {
        "id": str(raw_record.get("id") or ""),
        "step_index": raw_record.get("stepIndex", raw_record.get("step_index")),
        "name": str(raw_record.get("name") or ""),
        "arguments": arguments if isinstance(arguments, dict) else {},
        "output": raw_record.get("output"),
        "success": success,
        "state": state,
        "error_message": raw_record.get("errorMessage", raw_record.get("error_message")),
        "thought": str(raw_record.get("thought") or ""),
    }
    turn_index = _coerce_optional_int(raw_record.get("turnIndex", raw_record.get("turn_index")))
    if turn_index is not None:
        normalized["turn_index"] = turn_index
    assistant_id = str(raw_record.get("assistantId", raw_record.get("assistant_id")) or "").strip()
    if assistant_id:
        normalized["assistant_id"] = assistant_id
    for key in (
        "agentScope",
        "subagentId",
        "parentToolCallId",
        "parentAssistantId",
        "subagentTitle",
        "subagentTask",
    ):
        value = raw_record.get(key)
        if value is not None:
            normalized[key] = value
    return normalized


def upsert_tool(current: list[dict[str, Any]], next_tool: dict[str, Any]) -> list[dict[str, Any]]:
    for index, tool in enumerate(current):
        if tool["id"] == next_tool["id"]:
            updated = current[:]
            updated[index] = {**tool, **next_tool}
            return updated
    return [*current, next_tool]


def upsert_message(current: list[dict[str, Any]], next_message: dict[str, Any]) -> list[dict[str, Any]]:
    for index, message in enumerate(current):
        if message.get("id") == next_message.get("id"):
            updated = current[:]
            updated[index] = {**message, **next_message}
            return updated
    return [*current, next_message]


def update_plan_steps_for_tool(session: Any, step_index: int | None, tool_name: str) -> None:
    if not session.plan_steps:
        return

    if step_index is not None:
        for index, step in enumerate(session.plan_steps):
            numeric_id = index + 1
            if numeric_id < step_index:
                step["status"] = "completed"
            elif numeric_id == step_index:
                step["status"] = "running"
            elif step["status"] != "completed":
                step["status"] = "pending"

    steps_len = len(session.plan_steps)
    if getattr(session, "agent_type", "coding") == "deploy":
        if tool_name == "connect" and steps_len > 0:
            session.plan_steps[0]["description"] = "已发起部署连接，等待用户填写部署目标信息。"
        elif tool_name in {"list_files", "read_file"} and steps_len > 1:
            session.plan_steps[1]["description"] = "正在读取部署目录、配置文件和发布脚本。"
        elif tool_name in {"transfer_files", "execute", "excecute", "run_command"} and steps_len > 2:
            session.plan_steps[2]["description"] = "正在同步文件或执行部署命令，并收集结果。"
        return

    if tool_name in {"read_file", "list_file", "grep_file"} and steps_len > 1:
        session.plan_steps[1]["description"] = "已进入代码探索，正在读取结构、文件和引用关系。"
    elif tool_name in {"write_file", "replace_file"} and steps_len > 2:
        session.plan_steps[2]["description"] = "已开始落地修改，准备把变更写回工作区。"
    elif tool_name in {
        "execute",
        "excecute",
        "run_command",
        "start_task",
        "terminal_input",
        "terminal_wait",
        "task_input",
        "task_wait",
        "task_stop",
    } and steps_len > 3:
        session.plan_steps[3]["description"] = "正在执行命令并收集终端输出。"


def finalize_plan_steps(session: Any) -> None:
    for step in session.plan_steps:
        step["status"] = "completed"
    if session.plan_steps:
        session.plan_steps[-1]["description"] = "本轮执行结束，工具结果和最终答复都已沉淀。"


def chunk_text(text: str, chunk_size: int = 28) -> list[str]:
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)] or [""]


def extract_terminal_output(output: object) -> str | None:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        terminal_output = output.get("terminal_output")
        if isinstance(terminal_output, str):
            return terminal_output
        full_output = output.get("full_output")
        if isinstance(full_output, str):
            return full_output
    return None


def extract_preview_url(output: object) -> str | None:
    if isinstance(output, dict):
        resolved_url = output.get("resolved_url")
        if isinstance(resolved_url, str) and resolved_url.strip():
            return resolved_url
    return None
