from __future__ import annotations

import uuid
from typing import Any

from agent import ChatSession, ConversationMessage


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
) -> None:
    chat_session.state.conversation_messages = [
        ConversationMessage(
            role=str(message.get("role", "")),
            content=str(message.get("content", "")),
        )
        for message in history_messages
        if str(message.get("role", "")) in {"user", "assistant", "system"}
        and str(message.get("content", "")).strip()
    ]


def record_confirmation_result_for_agent(session: Any, content: str) -> None:
    if session.chat_session is None:
        return
    text = content.strip()
    if not text:
        return
    session.chat_session.state.conversation_messages.append(
        ConversationMessage(role="system", content=text)
    )


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
