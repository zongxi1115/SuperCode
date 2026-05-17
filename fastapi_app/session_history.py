from __future__ import annotations

import uuid
from typing import Any

from agent import ChatSession, ConversationMessage

MAX_PLANNING_RECORD_CHARS = 1_200


def ensure_user_message_recorded(session: Any, user_message: str) -> None:
    cleaned_message = user_message.strip()
    if not cleaned_message:
        return
    last_message = session.history_messages[-1] if session.history_messages else None
    if (
        isinstance(last_message, dict)
        and last_message.get("role") == "user"
        and str(last_message.get("content", "")).strip() == cleaned_message
    ):
        return
    session.history_messages.append(
        {"id": uuid.uuid4().hex, "role": "user", "content": cleaned_message}
    )
    session.touch()


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
    return {
        **message,
        "content": "".join(text_parts),
        "thoughts": "\n\n".join(thinking_parts),
        "toolCalls": tool_calls,
    }


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
        return sync_assistant_message_fields({**message, "parts": parts})

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


def seed_chat_session_history(
    chat_session: ChatSession,
    history_messages: list[dict[str, Any]],
    history_tools: list[dict[str, Any]] | None = None,
) -> None:
    chat_session.state.conversation_messages = [
        ConversationMessage(
            role=str(message.get("role", "")),
            content=str(message.get("content", "")),
        )
        for message in history_messages
        if str(message.get("role", "")) in {"user", "assistant"}
        and str(message.get("content", "")).strip()
    ]
    tool_records = build_tool_records_from_history(history_messages, history_tools or [])
    if tool_records:
        chat_session.state.data["tool_records"] = tool_records
    planning_records = build_planning_records_from_history(history_messages)
    if planning_records:
        chat_session.state.data["planning_records"] = planning_records


def record_confirmation_result_for_agent(session: Any, content: str) -> None:
    if session.chat_session is None:
        return
    text = content.strip()
    if not text:
        return
    records = list(session.chat_session.state.data.get("external_records", []))
    records.append(text)
    session.chat_session.state.data["external_records"] = records[-20:]


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

    for message in history_messages:
        raw_tool_calls = message.get("toolCalls")
        if isinstance(raw_tool_calls, list):
            for raw_tool_call in raw_tool_calls:
                if isinstance(raw_tool_call, dict):
                    upsert(raw_tool_call)
        raw_parts = message.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if not isinstance(part, dict):
                continue
            raw_tool_call = part.get("toolCall")
            if isinstance(raw_tool_call, dict):
                upsert(raw_tool_call)

    for raw_tool in history_tools:
        if isinstance(raw_tool, dict):
            upsert(raw_tool)

    return records


def build_planning_records_from_history(history_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for message_index, message in enumerate(history_messages, start=1):
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
    return {
        "id": str(raw_record.get("id") or ""),
        "step_index": raw_record.get("stepIndex", raw_record.get("step_index")),
        "name": str(raw_record.get("name") or ""),
        "arguments": arguments if isinstance(arguments, dict) else {},
        "output": raw_record.get("output"),
        "success": success,
        "state": state,
        "error_message": raw_record.get("errorMessage", raw_record.get("error_message")),
    }


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
                step["status"] = "in_progress"
            elif step["status"] != "completed":
                step["status"] = "pending"

    if tool_name in {"read_file", "list_file", "grep_file"}:
        session.plan_steps[1]["description"] = "已进入代码探索，正在读取结构、文件和引用关系。"
    elif tool_name in {"write_file", "replace_file"}:
        session.plan_steps[2]["description"] = "已开始落地修改，准备把变更写回工作区。"
    elif tool_name in {"execute", "excecute", "terminal_input", "terminal_wait"}:
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
