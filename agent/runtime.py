from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import events
from .model import ModelStreamUpdate
from .schema import AgentEvent, AgentResponse, AgentState, StepRecord, ToolCall, ToolResult
from .state import AgentStateView
from .tooling import ToolExecutor, ToolRegistry
from .tools import ToolContext


class AgentRuntime:
    """Runs the model -> tools -> observations loop for one agent turn."""

    def __init__(
        self,
        *,
        model: object,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        workspace: Path,
        max_steps: int,
        tool_context_metadata: dict[str, object],
    ) -> None:
        self.model = model
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.workspace = workspace
        self.max_steps = max_steps
        self.tool_context_metadata = tool_context_metadata

    def run_turn(
        self,
        state: AgentState,
        on_event: Callable[[AgentEvent], None] | None = None,
        continue_existing_turn: bool = False,
    ) -> AgentResponse:
        state_view = AgentStateView(state)
        history_steps = state_view.step_records
        turn_index = state_view.start_turn(
            continue_existing_turn=continue_existing_turn,
            include_thoughts=bool(self.tool_context_metadata.get("include_thoughts_in_context")),
        )
        steps: list[StepRecord] = []
        tool_definitions = self.tool_registry.definitions()
        context = ToolContext(
            workspace=self.workspace,
            metadata=self.tool_context_metadata,
        )
        emitter = events.AgentEventEmitter(on_event)
        emitter.emit(events.turn_started(state.current_input))

        index = state_view.first_step_index(
            turn_index,
            continue_existing_turn=continue_existing_turn,
        )
        while index <= self.max_steps:
            if self._is_cancelled(context):
                return self._build_cancelled_response(
                    state=state,
                    steps=steps,
                    history_steps=history_steps,
                    turn_index=turn_index,
                    step_index=index,
                    emitter=emitter,
                )

            on_model_stream = self._build_stream_handler(
                step_index=index,
                emitter=emitter,
            )
            step = self._next_model_step(
                state=state,
                tool_definitions=tool_definitions,
                on_stream=on_model_stream,
            )
            self._emit_latest_usage(index, emitter)
            emitter.emit(events.thought(index, step.thought))

            if self._is_cancelled(context):
                return self._build_cancelled_response(
                    state=state,
                    steps=steps,
                    history_steps=history_steps,
                    turn_index=turn_index,
                    step_index=index,
                    emitter=emitter,
                )

            if step.action == "final":
                step_record = StepRecord(
                    turn_index=turn_index,
                    index=index,
                    thought=step.thought,
                    final_answer=step.final_answer,
                )
                steps.append(step_record)
                history_steps.append(step_record)
                response = AgentResponse(
                    task=state.current_input,
                    final_output=step.final_answer or "",
                    steps=steps,
                )
                emitter.emit(events.final(index, step.thought, step.final_answer))
                emitter.emit(events.turn_finished(index, response.final_output))
                return response

            if step.action != "tool" or not step.tool_name:
                raise ValueError(f"不支持的决策动作: {step.action}")

            tool_calls = self.build_tool_calls(step, step_index=index)
            for tool_call in tool_calls:
                emitter.emit(
                    events.tool_call_started(
                        step_index=index,
                        step_thought=step.thought,
                        tool_call=tool_call,
                        parallel=len(tool_calls) > 1,
                    )
                )

            tool_results: list[ToolResult] = []

            def handle_tool_result(tool_call: ToolCall, result: ToolResult) -> None:
                state.add_tool_result(result)
                tool_results.append(result)
                emitter.emit(events.tool_result_ready(index, tool_call, result))

            self.tool_executor.execute_tool_calls(
                tool_calls,
                context,
                on_result=handle_tool_result,
            )

            step_record = StepRecord(
                turn_index=turn_index,
                index=index,
                thought=step.thought,
                tool_call=tool_calls[0] if len(tool_calls) == 1 else None,
                tool_result=tool_results[0] if len(tool_results) == 1 else None,
                tool_calls=tool_calls,
                tool_results=tool_results,
            )
            steps.append(step_record)
            history_steps.append(step_record)

            confirmation_pause = self._build_confirmation_pause_response(
                state=state,
                steps=steps,
                tool_results=tool_results,
            )
            if confirmation_pause is not None:
                return confirmation_pause

            if self._is_cancelled(context):
                return self._build_cancelled_response(
                    state=state,
                    steps=steps,
                    history_steps=history_steps,
                    turn_index=turn_index,
                    step_index=index,
                    emitter=emitter,
                )
            index += 1

        return self._build_limit_response(
            state=state,
            steps=steps,
            history_steps=history_steps,
            turn_index=turn_index,
            step_index=index,
            emitter=emitter,
        )

    def _next_model_step(
        self,
        *,
        state: AgentState,
        tool_definitions: dict[str, dict[str, object]],
        on_stream: Callable[[ModelStreamUpdate], None] | None,
    ) -> object:
        next_step = getattr(self.model, "next_step", None)
        if callable(next_step):
            return next_step(
                state=state,
                tool_definitions=tool_definitions,
                on_stream=on_stream,
            )

        raise TypeError("model 必须提供 next_step(...) 方法。")

    def _build_stream_handler(
        self,
        *,
        step_index: int,
        emitter: events.AgentEventEmitter,
    ) -> Callable[[ModelStreamUpdate], None]:
        streamed_final_answer = ""
        streamed_thought = ""
        streamed_tool_input = ""
        streamed_tool_input_started = False
        streamed_tool_input_key: tuple[str, str] | None = None

        def on_model_stream(update: ModelStreamUpdate) -> None:
            nonlocal streamed_final_answer, streamed_thought
            nonlocal streamed_tool_input, streamed_tool_input_started, streamed_tool_input_key

            if update.thought:
                if update.thought.startswith(streamed_thought):
                    thought_delta_value = update.thought[len(streamed_thought) :]
                else:
                    thought_delta_value = update.thought

                if thought_delta_value:
                    streamed_thought = update.thought
                    emitter.emit(
                        events.thought_delta(
                            step_index,
                            update.thought,
                            thought_delta_value,
                        )
                    )

            if (
                update.streamed_tool_name
                and update.streamed_tool_argument_name
                and update.streamed_tool_input is not None
            ):
                tool_name = update.streamed_tool_name
                argument_name = update.streamed_tool_argument_name
                tool_id = f"step-{step_index}-tool-1-{tool_name}"
                next_key = (tool_name, argument_name)

                if streamed_tool_input_key != next_key:
                    streamed_tool_input = ""
                    streamed_tool_input_started = False
                    streamed_tool_input_key = next_key

                if update.streamed_tool_input.startswith(streamed_tool_input):
                    tool_input_delta_value = update.streamed_tool_input[len(streamed_tool_input) :]
                else:
                    tool_input_delta_value = update.streamed_tool_input

                if tool_input_delta_value:
                    tool_call = ToolCall(
                        id=tool_id,
                        name=tool_name,
                        arguments={"streamed_argument": argument_name},
                    )
                    if not streamed_tool_input_started:
                        streamed_tool_input_started = True
                        emitter.emit(events.tool_input_started(step_index, tool_call))

                    streamed_tool_input = update.streamed_tool_input
                    emitter.emit(
                        events.tool_input_delta(
                            step_index,
                            tool_call,
                            tool_input_delta_value,
                        )
                    )

            if update.action != "final" or update.final_answer is None:
                return

            if update.final_answer.startswith(streamed_final_answer):
                delta = update.final_answer[len(streamed_final_answer) :]
            else:
                delta = update.final_answer

            if not delta:
                return

            streamed_final_answer = update.final_answer
            emitter.emit(
                events.final_answer_delta(
                    step_index,
                    update.thought,
                    update.final_answer,
                    delta,
                )
            )

        return on_model_stream

    def _emit_latest_usage(self, step_index: int, emitter: events.AgentEventEmitter) -> None:
        latest_usage_getter = getattr(self.model, "latest_usage", None)
        latest_usage = latest_usage_getter() if callable(latest_usage_getter) else None
        if latest_usage:
            emitter.emit(events.usage(step_index, latest_usage))

    def build_tool_calls(self, step: object, step_index: int) -> list[ToolCall]:
        raw_calls = step.normalized_tool_calls()
        tool_calls: list[ToolCall] = []
        for position, raw_call in enumerate(raw_calls, start=1):
            tool_name = str(raw_call.get("tool_name", "")).strip()
            if not tool_name:
                raise ValueError("工具调用缺少 tool_name。")

            tool_arguments = raw_call.get("tool_arguments", {})
            if not isinstance(tool_arguments, dict):
                raise ValueError("工具调用里的 tool_arguments 必须是对象。")

            tool_calls.append(
                ToolCall(
                    id=f"step-{step_index}-tool-{position}-{tool_name}",
                    name=tool_name,
                    arguments=tool_arguments,
                )
            )

        if not tool_calls:
            raise ValueError("模型决定调用工具，但没有返回有效工具列表。")
        return tool_calls

    def _build_confirmation_pause_response(
        self,
        *,
        state: AgentState,
        steps: list[StepRecord],
        tool_results: list[ToolResult],
    ) -> AgentResponse | None:
        for tool_result in tool_results:
            if not self.requires_user_confirmation(tool_result):
                continue

            return AgentResponse(
                task=state.current_input,
                final_output="",
                steps=steps,
            )

        return None

    @staticmethod
    def requires_user_confirmation(tool_result: ToolResult) -> bool:
        return bool(
            tool_result.success
            and isinstance(tool_result.output, dict)
            and (
                tool_result.output.get("requires_confirmation") is True
                or tool_result.output.get("requires_user_input") is True
            )
        )

    def _is_cancelled(self, context: ToolContext) -> bool:
        return self.tool_executor.is_cancelled(context)

    def _build_cancelled_response(
        self,
        *,
        state: AgentState,
        steps: list[StepRecord],
        history_steps: list[StepRecord],
        turn_index: int,
        step_index: int,
        emitter: events.AgentEventEmitter,
    ) -> AgentResponse:
        final_output = "已停止当前任务。"
        step_record = StepRecord(
            turn_index=turn_index,
            index=step_index,
            thought="用户主动停止了当前执行。",
            final_answer=final_output,
        )
        steps.append(step_record)
        history_steps.append(step_record)
        response = AgentResponse(
            task=state.current_input,
            final_output=final_output,
            steps=steps,
        )
        emitter.emit(
            AgentEvent(
                type="final",
                step_index=step_index,
                message="当前任务已停止。",
                final_answer=final_output,
            )
        )
        emitter.emit(
            events.turn_finished(
                step_index,
                final_output,
                message="本轮处理已停止。",
            )
        )
        return response

    def _build_limit_response(
        self,
        *,
        state: AgentState,
        steps: list[StepRecord],
        history_steps: list[StepRecord],
        turn_index: int,
        step_index: int,
        emitter: events.AgentEventEmitter,
    ) -> AgentResponse:
        final_output = (
            f"本轮已执行 {self.max_steps} 步仍未收敛，我先停止，避免继续重复调用工具。"
            "你可以补充更明确的目标后让我继续。"
        )
        step_record = StepRecord(
            turn_index=turn_index,
            index=step_index,
            thought="达到单轮安全步数上限，停止继续执行。",
            final_answer=final_output,
        )
        steps.append(step_record)
        history_steps.append(step_record)
        response = AgentResponse(
            task=state.current_input,
            final_output=final_output,
            steps=steps,
        )
        emitter.emit(events.limit_reached(step_index, final_output))
        emitter.emit(
            events.turn_finished(
                step_index,
                response.final_output,
                message="本轮处理结束，但模型没有自然收敛。",
            )
        )
        return response


__all__ = ["AgentRuntime"]
