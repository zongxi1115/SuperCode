from __future__ import annotations

import time
import uuid
from typing import Any

from agent import ChatSession, ConversationMessage, StepRecord, ToolResult

MAX_PLANNING_RECORD_CHARS = 1_200
MAX_STORED_TOOL_RECORDS = 80
SUBAGENT_SCOPE = "subagent"


def is_subagent_record(record: dict[str, Any]) -> bool:
    return str(record.get("agentScope", record.get("agent_scope")) or "").strip() == SUBAGENT_SCOPE


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
            reasoning_content=(
                extract_message_thought_text(message)
                if str(message.get("role", "")) == "assistant"
                else None
            ) or None,
        )
        for message in history_messages
        if str(message.get("role", "")) in {"user", "assistant"}
        and str(message.get("content", "")).strip()
        and not is_subagent_record(message)
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

    for message in history_messages:
        if is_subagent_record(message):
            continue
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
    }
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
        elif tool_name in {"transfer_files", "execute"} and steps_len > 2:
            session.plan_steps[2]["description"] = "正在同步文件或执行部署命令，并收集结果。"
        return

    if tool_name in {"read_file", "list_file", "grep_file"} and steps_len > 1:
        session.plan_steps[1]["description"] = "已进入代码探索，正在读取结构、文件和引用关系。"
    elif tool_name in {"write_file", "replace_file"} and steps_len > 2:
        session.plan_steps[2]["description"] = "已开始落地修改，准备把变更写回工作区。"
    elif tool_name in {"execute", "excecute", "terminal_input", "terminal_wait"} and steps_len > 3:
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
