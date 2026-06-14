from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent import events
from agent.schema import AgentEvent, AgentResponse, AgentState, ConversationMessage, StepRecord, ToolCall, ToolResult
from agent.state import AgentStateView
from zonix import (
    Agent as ZonixAgent,
    ErrorEvent,
    Finish,
    ReasoningDelta,
    TextDelta,
    ToolInputAvailable,
    ToolInputDelta,
    ToolInputStart,
    ToolOutputAvailable,
)
from zonix.content import content_text, image_part, text_part
from zonix.runtime import run_node
from zonix.types import Message as ZonixMessage
from zonix.types import Usage as ZonixUsage

MAX_STORED_TOOL_RECORDS = 80
MAX_STORED_PLANNING_RECORDS = 80
MAX_PLANNING_RECORD_CHARS = 1_200


@dataclass(slots=True)
class SuperCodeRunContext:
    workspace: Path
    metadata: dict[str, Any]
    state: AgentState


@dataclass(slots=True)
class ConversationTurn:
    user_message: str
    assistant_message: str
    response: AgentResponse


@dataclass(slots=True)
class _PendingStep:
    turn_index: int
    index: int
    thought: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(slots=True)
class ZonixChatSession:
    agent: ZonixAgent
    task: str = "你是一个可以帮助用户理解和修改项目的编码智能体。"
    state: AgentState = field(init=False)
    turns: list[ConversationTurn] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.state = AgentState(task=self.task)

    def ask(
        self,
        user_message: str,
        on_event: Callable[[AgentEvent], None] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> AgentResponse:
        cleaned_message = user_message.strip()
        image_attachments = _normalize_image_attachments(attachments)
        if not cleaned_message and not image_attachments:
            raise ValueError("用户消息不能为空。")

        self.state.current_input = cleaned_message
        self.state.data["current_input_attachments"] = image_attachments
        self.state.conversation_messages.append(
            ConversationMessage(
                role="user",
                content=cleaned_message,
                attachments=image_attachments,
            )
        )

        try:
            response = ZonixAgentRunner(self.agent).run_turn(self.state, on_event=on_event)
        finally:
            self.state.data.pop("current_input_attachments", None)
        self._record_response(cleaned_message, response)
        return response

    def continue_turn(
        self,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
        response = ZonixAgentRunner(self.agent).run_turn(
            self.state,
            on_event=on_event,
            continue_existing_turn=True,
        )
        self._record_response("", response)
        return response

    def clear(self) -> None:
        self.state = AgentState(task=self.task)
        self.turns.clear()

    def _record_response(self, user_message: str, response: AgentResponse) -> None:
        if response.final_output.strip():
            assistant_reasoning = self._assistant_reasoning_from_response(response)
            self.state.conversation_messages.append(
                ConversationMessage(
                    role="assistant",
                    content=response.final_output,
                    reasoning_content=assistant_reasoning or None,
                )
            )
        self._append_execution_records(response)
        if user_message and response.final_output.strip():
            self.turns.append(
                ConversationTurn(
                    user_message=user_message,
                    assistant_message=response.final_output,
                    response=response,
                )
            )

    def _append_execution_records(self, response: AgentResponse) -> None:
        self._append_tool_records(response)
        self._append_planning_records(response)

    def _assistant_reasoning_from_response(self, response: AgentResponse) -> str:
        thoughts: list[str] = []
        for step in response.steps:
            thought = " ".join(step.thought.split()).strip()
            if not thought or (thoughts and thoughts[-1] == thought):
                continue
            thoughts.append(thought)
        return "\n\n".join(thoughts)

    def _append_tool_records(self, response: AgentResponse) -> None:
        state_view = AgentStateView(self.state)
        next_records = list(state_view.tool_records)
        for step in response.steps:
            next_records.extend(self._records_from_step(step))
        if next_records:
            self.state.data["tool_records"] = next_records[-MAX_STORED_TOOL_RECORDS:]

    def _records_from_step(self, step: StepRecord) -> list[dict[str, object]]:
        tool_calls = step.tool_calls or ([step.tool_call] if step.tool_call is not None else [])
        tool_results = step.tool_results or ([step.tool_result] if step.tool_result is not None else [])
        results_by_id = {
            result.tool_call_id: result
            for result in tool_results
            if result is not None and result.tool_call_id
        }
        records: list[dict[str, object]] = []
        seen_result_ids: set[str | None] = set()
        for tool_call in tool_calls:
            if tool_call is None:
                continue
            result = results_by_id.get(tool_call.id)
            if result is not None:
                seen_result_ids.add(result.tool_call_id)
            records.append(self._tool_record(step, tool_call, result))
        for result in tool_results:
            if result is None or result.tool_call_id in seen_result_ids:
                continue
            records.append(self._tool_record(step, None, result))
        return records

    def _tool_record(
        self,
        step: StepRecord,
        tool_call: ToolCall | None,
        tool_result: ToolResult | None,
    ) -> dict[str, object]:
        name = tool_call.name if tool_call is not None else (tool_result.name if tool_result else "")
        tool_id = (
            tool_call.id
            if tool_call is not None and tool_call.id
            else tool_result.tool_call_id if tool_result is not None else None
        )
        success = tool_result.success if tool_result is not None else None
        state = "completed" if success is True else "error" if success is False else "running"
        return {
            "turn_index": step.turn_index,
            "step_index": step.index,
            "id": tool_id,
            "name": name,
            "arguments": tool_call.arguments if tool_call is not None else {},
            "output": tool_result.output if tool_result is not None else None,
            "success": success,
            "state": state,
            "error_message": tool_result.error_message if tool_result is not None else None,
        }

    def _append_planning_records(self, response: AgentResponse) -> None:
        state_view = AgentStateView(self.state)
        next_records = list(state_view.planning_records)
        for step in response.steps:
            record = self._planning_record(step)
            if record is not None:
                next_records.append(record)
        if next_records:
            self.state.data["planning_records"] = next_records[-MAX_STORED_PLANNING_RECORDS:]

    def _planning_record(self, step: StepRecord) -> dict[str, object] | None:
        thought = " ".join(step.thought.split()).strip()
        if not thought:
            return None
        tool_calls = step.tool_calls or ([step.tool_call] if step.tool_call is not None else [])
        tools = [tool_call.name for tool_call in tool_calls if tool_call is not None]
        if len(thought) > MAX_PLANNING_RECORD_CHARS:
            thought = f"{thought[:MAX_PLANNING_RECORD_CHARS].rstrip()}... [truncated]"
        return {
            "turn_index": step.turn_index,
            "step_index": step.index,
            "thought": thought,
            "action": "final" if step.final_answer else "tool" if tools else "observe",
            "tools": tools,
        }


class ZonixAgentRunner:
    def __init__(self, agent: ZonixAgent) -> None:
        self.agent = agent

    def run_turn(
        self,
        state: AgentState,
        on_event: Callable[[AgentEvent], None] | None = None,
        continue_existing_turn: bool = False,
    ) -> AgentResponse:
        return _run_async_blocking(
            lambda: self._run_turn_async(
                state,
                on_event=on_event,
                continue_existing_turn=continue_existing_turn,
            )
        )

    async def _run_turn_async(
        self,
        state: AgentState,
        *,
        on_event: Callable[[AgentEvent], None] | None,
        continue_existing_turn: bool,
    ) -> AgentResponse:
        workspace = Path(getattr(self.agent, "workspace", ".")).resolve()
        metadata = dict(getattr(self.agent, "tool_context_metadata", {}) or {})
        recorder = ZonixEventRecorder(
            state=state,
            metadata=metadata,
            continue_existing_turn=continue_existing_turn,
            on_event=on_event,
        )
        recorder.emit(events.turn_started(state.current_input))
        task_content = _zonix_content_from_text_and_attachments(
            state.current_input,
            state.data.get("current_input_attachments"),
        )
        await run_node(
            self.agent,
            task_content,
            ctx=SuperCodeRunContext(workspace=workspace, metadata=metadata, state=state),
            message_history=_zonix_message_history_from_state(state),
            emit=recorder.publish,
        )
        return recorder.response()


class ZonixEventRecorder:
    def __init__(
        self,
        *,
        state: AgentState,
        metadata: dict[str, Any],
        continue_existing_turn: bool,
        on_event: Callable[[AgentEvent], None] | None,
    ) -> None:
        self.state = state
        self.metadata = metadata
        self.on_event = on_event
        self.state_view = AgentStateView(state)
        self.history_steps = self.state_view.step_records
        self.turn_index = self.state_view.start_turn(
            continue_existing_turn=continue_existing_turn,
            include_thoughts=bool(metadata.get("include_thoughts_in_context")),
        )
        self.next_step_index = self.state_view.first_step_index(
            self.turn_index,
            continue_existing_turn=continue_existing_turn,
        )
        self.steps: list[StepRecord] = []
        self.pending_step: _PendingStep | None = None
        self.tool_calls_by_id: dict[str, ToolCall] = {}
        self.tool_names_by_id: dict[str, str] = {}
        self.thought_by_step: dict[int, str] = {}
        self.current_text = ""
        self.final_output = ""
        self.finished = False
        self.paused = False

    def emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)

    async def publish(self, event: Any) -> None:
        if isinstance(event, ReasoningDelta):
            self._record_reasoning_delta(event.delta)
        elif isinstance(event, TextDelta):
            self._record_text_delta(event.delta)
        elif isinstance(event, ToolInputStart):
            self._record_tool_input_start(event)
        elif isinstance(event, ToolInputDelta):
            self._record_tool_input_delta(event)
        elif isinstance(event, ToolInputAvailable):
            self._record_tool_input_available(event)
        elif isinstance(event, ToolOutputAvailable):
            self._record_tool_output(event)
        elif isinstance(event, Finish):
            self._record_finish(event.output, event.usage)
        elif isinstance(event, ErrorEvent):
            raise RuntimeError(event.message)

    def response(self) -> AgentResponse:
        return AgentResponse(
            task=self.state.current_input,
            final_output=self.final_output,
            steps=self.steps,
        )

    def _current_step_index(self) -> int:
        return self.pending_step.index if self.pending_step is not None else self.next_step_index

    def _ensure_pending_step(self) -> _PendingStep:
        if self.pending_step is None:
            self.pending_step = _PendingStep(
                turn_index=self.turn_index,
                index=self.next_step_index,
                thought=self.thought_by_step.get(self.next_step_index, ""),
            )
        return self.pending_step

    def _record_reasoning_delta(self, delta: str) -> None:
        if not delta:
            return
        step_index = self._current_step_index()
        thought = f"{self.thought_by_step.get(step_index, '')}{delta}"
        self.thought_by_step[step_index] = thought
        if self.pending_step is not None:
            self.pending_step.thought = thought
        self.emit(events.thought_delta(step_index, thought, delta))

    def _record_text_delta(self, delta: str) -> None:
        if not delta:
            return
        step_index = self._current_step_index()
        self.current_text += delta
        self.emit(
            events.final_answer_delta(
                step_index,
                self.thought_by_step.get(step_index),
                self.current_text,
                delta,
            )
        )

    def _record_tool_input_start(self, event: ToolInputStart) -> None:
        self.tool_names_by_id[event.call_id] = event.tool
        self.emit(
            events.tool_input_started(
                self._current_step_index(),
                ToolCall(id=event.call_id, name=event.tool, arguments={}),
            )
        )

    def _record_tool_input_delta(self, event: ToolInputDelta) -> None:
        self.emit(
            events.tool_input_delta(
                self._current_step_index(),
                ToolCall(
                    id=event.call_id,
                    name=self.tool_names_by_id.get(event.call_id, ""),
                    arguments={},
                ),
                event.delta,
            )
        )

    def _record_tool_input_available(self, event: ToolInputAvailable) -> None:
        pending = self._ensure_pending_step()
        tool_call = ToolCall(
            id=event.call_id,
            name=event.tool,
            arguments=event.input if isinstance(event.input, dict) else {},
        )
        self.tool_names_by_id[event.call_id] = event.tool
        self.tool_calls_by_id[event.call_id] = tool_call
        if not any(existing.id == event.call_id for existing in pending.tool_calls):
            pending.tool_calls.append(tool_call)
        self.emit(
            events.tool_call_started(
                step_index=pending.index,
                step_thought=pending.thought,
                tool_call=tool_call,
                parallel=len(pending.tool_calls) > 1,
            )
        )

    def _record_tool_output(self, event: ToolOutputAvailable) -> None:
        pending = self._ensure_pending_step()
        tool_call = self.tool_calls_by_id.get(event.call_id)
        if tool_call is None:
            tool_call = ToolCall(
                id=event.call_id,
                name=self.tool_names_by_id.get(event.call_id, ""),
                arguments={},
            )
            self.tool_calls_by_id[event.call_id] = tool_call
            pending.tool_calls.append(tool_call)

        tool_result = _tool_result_from_output(tool_call, event.output)
        self.state.add_tool_result(tool_result)
        pending.tool_results.append(tool_result)
        self.emit(events.tool_result_ready(pending.index, tool_call, tool_result))
        if _requires_user_confirmation(tool_result):
            self.paused = True
        if len(pending.tool_results) >= len(pending.tool_calls):
            self._finalize_pending_step()

    def _finalize_pending_step(self) -> None:
        pending = self.pending_step
        if pending is None:
            return
        thought = self.thought_by_step.get(pending.index, pending.thought)
        if thought:
            self.emit(events.thought(pending.index, thought))
        step_record = StepRecord(
            turn_index=pending.turn_index,
            index=pending.index,
            thought=thought,
            tool_call=pending.tool_calls[0] if len(pending.tool_calls) == 1 else None,
            tool_result=pending.tool_results[0] if len(pending.tool_results) == 1 else None,
            tool_calls=pending.tool_calls,
            tool_results=pending.tool_results,
        )
        self.steps.append(step_record)
        self.history_steps.append(step_record)
        self.pending_step = None
        self.next_step_index = pending.index + 1

    def _record_finish(self, output: Any, usage: ZonixUsage) -> None:
        if self.finished:
            return
        if self.pending_step is not None:
            self._finalize_pending_step()
        if self.paused:
            self.final_output = ""
            self.finished = True
            return
        final_output = str(output or self.current_text or "")
        self.final_output = final_output
        step_index = self.next_step_index
        usage_payload = _usage_payload(usage)
        if any(usage_payload.values()):
            self.emit(events.usage(step_index, usage_payload))
        thought = self.thought_by_step.get(step_index, "")
        step_record = StepRecord(
            turn_index=self.turn_index,
            index=step_index,
            thought=thought,
            final_answer=final_output,
        )
        self.steps.append(step_record)
        self.history_steps.append(step_record)
        self.emit(events.final(step_index, thought, final_output))
        self.emit(events.turn_finished(step_index, final_output))
        self.finished = True


def _tool_result_from_output(tool_call: ToolCall, raw_output: Any) -> ToolResult:
    if isinstance(raw_output, dict) and raw_output.get("success") is False:
        return ToolResult(
            name=tool_call.name,
            output=raw_output.get("output"),
            tool_call_id=tool_call.id,
            success=False,
            error_message=str(raw_output.get("error_message") or raw_output.get("error") or ""),
        )
    return ToolResult(
        name=tool_call.name,
        output=raw_output,
        tool_call_id=tool_call.id,
        success=True,
    )


def _requires_user_confirmation(tool_result: ToolResult) -> bool:
    return bool(
        tool_result.success
        and isinstance(tool_result.output, dict)
        and (
            tool_result.output.get("requires_confirmation") is True
            or tool_result.output.get("requires_user_input") is True
        )
    )


def _usage_payload(usage: ZonixUsage) -> dict[str, int]:
    return {
        "inputTokens": usage.input_tokens,
        "outputTokens": usage.output_tokens,
        "reasoningTokens": 0,
        "cachedInputTokens": 0,
        "totalTokens": usage.total_tokens or usage.input_tokens + usage.output_tokens,
    }


def _normalize_image_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []

    attachments: list[dict[str, Any]] = []
    for item in raw_attachments:
        if not isinstance(item, dict):
            continue
        data_url = str(item.get("dataUrl") or item.get("data_url") or item.get("url") or "").strip()
        media_type = str(item.get("mediaType") or item.get("media_type") or "").strip()
        if not data_url:
            continue
        if media_type and not media_type.startswith("image/"):
            continue
        if not media_type and data_url.startswith("data:image/"):
            media_type = data_url.split(";", 1)[0].removeprefix("data:")
        attachments.append(
            {
                "id": str(item.get("id") or ""),
                "type": "image",
                "filename": str(item.get("filename") or item.get("name") or ""),
                "mediaType": media_type or "image/png",
                "dataUrl": data_url,
            }
        )
    return attachments


def _zonix_content_from_text_and_attachments(
    text: str,
    attachments: Any,
) -> str | list[dict[str, Any]]:
    image_attachments = _normalize_image_attachments(attachments)
    if not image_attachments:
        return text

    parts: list[dict[str, Any]] = []
    if text:
        parts.append(text_part(text))
    for attachment in image_attachments:
        parts.append(
            image_part(
                str(attachment.get("dataUrl") or ""),
                media_type=str(attachment.get("mediaType") or "image/png"),
                filename=str(attachment.get("filename") or ""),
            )
        )
    return parts


def _zonix_message_history_from_state(state: AgentState) -> list[ZonixMessage]:
    current_input = state.current_input.strip()
    messages: list[ZonixMessage] = []
    for message in state.conversation_messages:
        role = str(getattr(message, "role", "")).strip()
        content = str(getattr(message, "content", "") or "").strip()
        attachments = _normalize_image_attachments(getattr(message, "attachments", None))
        if role not in {"user", "assistant"} or (not content and not attachments):
            continue
        data: dict[str, Any] = {}
        reasoning_content = str(getattr(message, "reasoning_content", "") or "").strip()
        if role == "assistant" and reasoning_content:
            data["reasoning_content"] = reasoning_content
        messages.append(
            ZonixMessage(
                role=role,
                content=_zonix_content_from_text_and_attachments(content, attachments),
                data=data,
            )
        )
    if (
        messages
        and messages[-1].role == "user"
        and current_input
        and content_text(messages[-1].content).strip() == current_input
    ):
        return messages[:-1]
    return messages


def _run_async_blocking(coro_factory: Callable[[], Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 - propagate from worker thread
            error["value"] = exc

    thread = threading.Thread(target=runner)
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


__all__ = ["ConversationTurn", "SuperCodeRunContext", "ZonixAgentRunner", "ZonixChatSession"]
