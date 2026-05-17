from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .brain import AgentBrain, BrainStreamingUpdate
from .schema import AgentEvent, AgentResponse, AgentState, StepRecord, ToolCall, ToolResult
from .tools import BaseTool, ToolContext


DEFAULT_MAX_STEPS = 40


class CodingAgent:
    """简单编码智能体。

    设计重点：
    1. 对外只暴露一个好用的 `run(task)`。
    2. 内部保留清晰的“决策 -> 工具 -> 观察”循环。
    3. 后续既能替换 brain，也能逐步增加工具，而不用推翻接口。
    """

    def __init__(
        self,
        brain: AgentBrain,
        tools: list[BaseTool],
        workspace: str | Path = ".",
        max_steps: int | None = None,
        tool_context_metadata: dict[str, Any] | None = None,
    ) -> None:
        """初始化智能体。

        参数说明：
        - `brain`：负责决定下一步动作的对象
        - `tools`：可供调用的工具列表
        - `workspace`：工具默认操作的工作目录
        - `max_steps`：单轮最大执行步数，防止模型在已完成后仍反复继续
        """

        self.brain = brain
        self.workspace = Path(workspace).resolve()
        self.max_steps = max(1, max_steps or DEFAULT_MAX_STEPS)
        self.tools = {tool.name: tool for tool in tools}
        self.tool_context_metadata = tool_context_metadata or {}

    def run(
        self,
        task: str,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
        """执行一个单轮任务并返回最终结果。"""

        state = AgentState(
            task="你是一个编码智能体，请围绕用户当前这一次请求直接完成任务。",
            current_input=task,
            conversation_messages=[],
        )
        return self.run_turn(state, on_event=on_event)

    def run_turn(
        self,
        state: AgentState,
        on_event: Callable[[AgentEvent], None] | None = None,
        continue_existing_turn: bool = False,
    ) -> AgentResponse:
        """在已有状态上执行当前这一轮。

        这个方法用于多轮对话场景。
        它会保留会话历史，但会清空“本轮工具轨迹”，避免把上一轮工具结果误当成当前轮上下文。
        """

        history_steps = state.data.setdefault("step_records", [])
        if continue_existing_turn and state.data.get("turn_index") is not None:
            turn_index = int(state.data.get("turn_index", 0))
        else:
            turn_index = int(state.data.get("turn_index", 0)) + 1
        state.data["turn_index"] = turn_index
        state.data["include_thoughts_in_context"] = bool(
            self.tool_context_metadata.get("include_thoughts_in_context")
        )
        steps: list[StepRecord] = []
        state.tool_results = []
        tool_definitions = {
            name: {
                "description": tool.description,
                "parameters_schema": getattr(tool, "parameters_schema", None),
            }
            for name, tool in self.tools.items()
        }
        context = ToolContext(
            workspace=self.workspace,
            metadata=self.tool_context_metadata,
        )
        self._emit_event(
            on_event,
            AgentEvent(
                type="turn_started",
                message=f"开始处理本轮请求：{state.current_input}",
            ),
        )

        if continue_existing_turn:
            current_turn_indices = [
                step.index
                for step in history_steps
                if isinstance(step, StepRecord) and step.turn_index == turn_index
            ]
            index = (max(current_turn_indices) + 1) if current_turn_indices else 1
        else:
            index = 1
        while index <= self.max_steps:
            if self._is_cancelled(context):
                return self._build_cancelled_response(
                    state=state,
                    steps=steps,
                    history_steps=history_steps,
                    turn_index=turn_index,
                    step_index=index,
                    on_event=on_event,
                )

            streamed_final_answer = ""
            streamed_thought = ""
            streamed_tool_input = ""
            streamed_tool_input_started = False
            streamed_tool_input_key: tuple[str, str] | None = None

            def on_brain_stream(update: BrainStreamingUpdate) -> None:
                nonlocal streamed_final_answer, streamed_thought
                nonlocal streamed_tool_input, streamed_tool_input_started, streamed_tool_input_key

                if update.thought:
                    if update.thought.startswith(streamed_thought):
                        thought_delta = update.thought[len(streamed_thought) :]
                    else:
                        thought_delta = update.thought

                    if thought_delta:
                        streamed_thought = update.thought
                        self._emit_event(
                            on_event,
                            AgentEvent(
                                type="thought_delta",
                                step_index=index,
                                message=f"第 {index} 步正在流式输出思考。",
                                thought=update.thought,
                                delta=thought_delta,
                            ),
                        )

                if (
                    update.streamed_tool_name
                    and update.streamed_tool_argument_name
                    and update.streamed_tool_input is not None
                ):
                    tool_name = update.streamed_tool_name
                    argument_name = update.streamed_tool_argument_name
                    tool_id = f"step-{index}-tool-1-{tool_name}"
                    next_key = (tool_name, argument_name)

                    if streamed_tool_input_key != next_key:
                        streamed_tool_input = ""
                        streamed_tool_input_started = False
                        streamed_tool_input_key = next_key

                    if update.streamed_tool_input.startswith(streamed_tool_input):
                        tool_input_delta = update.streamed_tool_input[len(streamed_tool_input) :]
                    else:
                        tool_input_delta = update.streamed_tool_input

                    if tool_input_delta:
                        tool_call = ToolCall(
                            id=tool_id,
                            name=tool_name,
                            arguments={"streamed_argument": argument_name},
                        )
                        if not streamed_tool_input_started:
                            streamed_tool_input_started = True
                            self._emit_event(
                                on_event,
                                AgentEvent(
                                    type="tool_input_started",
                                    step_index=index,
                                    message=f"第 {index} 步开始流式生成工具 {tool_name} 的输入。",
                                    tool_call=tool_call,
                                ),
                            )

                        streamed_tool_input = update.streamed_tool_input
                        self._emit_event(
                            on_event,
                            AgentEvent(
                                type="tool_input_delta",
                                step_index=index,
                                message=f"第 {index} 步正在流式生成工具 {tool_name} 的输入。",
                                tool_call=tool_call,
                                delta=tool_input_delta,
                            ),
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
                self._emit_event(
                    on_event,
                    AgentEvent(
                        type="final_answer_delta",
                        step_index=index,
                        message=f"第 {index} 步正在流式输出最终答复。",
                        thought=update.thought,
                        final_answer=update.final_answer,
                        delta=delta,
                    ),
                )

            decision = self.brain.decide(
                state=state,
                tool_definitions=tool_definitions,
                on_stream=on_brain_stream,
            )
            self._emit_event(
                on_event,
                AgentEvent(
                    type="thought",
                    step_index=index,
                    message=f"第 {index} 步正在思考。",
                    thought=decision.thought,
                ),
            )

            if self._is_cancelled(context):
                return self._build_cancelled_response(
                    state=state,
                    steps=steps,
                    history_steps=history_steps,
                    turn_index=turn_index,
                    step_index=index,
                    on_event=on_event,
                )

            if decision.action == "final":
                step_record = StepRecord(
                    turn_index=turn_index,
                    index=index,
                    thought=decision.thought,
                    final_answer=decision.final_answer,
                )
                steps.append(step_record)
                history_steps.append(step_record)
                response = AgentResponse(
                    task=state.current_input,
                    final_output=decision.final_answer or "",
                    steps=steps,
                )
                self._emit_event(
                    on_event,
                    AgentEvent(
                        type="final",
                        step_index=index,
                        message="本轮已得到最终答案。",
                        thought=decision.thought,
                        final_answer=decision.final_answer,
                    ),
                )
                self._emit_event(
                    on_event,
                    AgentEvent(
                        type="turn_finished",
                        step_index=index,
                        message="本轮处理完成。",
                        final_answer=response.final_output,
                    ),
                )
                return response

            if decision.action != "tool" or not decision.tool_name:
                raise ValueError(f"不支持的决策动作: {decision.action}")

            tool_calls = self._build_tool_calls(decision, step_index=index)
            for tool_call in tool_calls:
                self._emit_event(
                    on_event,
                    AgentEvent(
                        type="tool_call",
                        step_index=index,
                        message=(
                            f"第 {index} 步准备并行调用工具 {tool_call.name}。"
                            if len(tool_calls) > 1
                            else f"第 {index} 步准备调用工具 {tool_call.name}。"
                        ),
                        thought=decision.thought,
                        tool_call=tool_call,
                    ),
                )

            tool_results: list[ToolResult] = []

            def handle_tool_result(tool_call: ToolCall, result: ToolResult) -> None:
                state.add_tool_result(result)
                tool_results.append(result)
                self._emit_event(
                    on_event,
                    AgentEvent(
                        type="tool_result",
                        step_index=index,
                        message=f"第 {index} 步工具 {tool_call.name} 已返回结果。",
                        tool_call=tool_call,
                        tool_result=result,
                    ),
                )

            self._execute_tool_calls(
                tool_calls,
                context,
                on_result=handle_tool_result,
            )

            step_record = StepRecord(
                turn_index=turn_index,
                index=index,
                thought=decision.thought,
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
                turn_index=turn_index,
                step_index=index,
                tool_calls=tool_calls,
                tool_results=tool_results,
                on_event=on_event,
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
                    on_event=on_event,
                )
            index += 1

        return self._build_limit_response(
            state=state,
            steps=steps,
            history_steps=history_steps,
            turn_index=turn_index,
            step_index=index,
            on_event=on_event,
        )

    def _execute_tool(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        """执行单个工具调用，并把异常包装成统一结果。"""

        if self._is_cancelled(context):
            return ToolResult(
                name=tool_call.name,
                output=None,
                tool_call_id=tool_call.id,
                success=False,
                error_message="当前任务已被用户停止。",
            )

        tool = self.tools.get(tool_call.name)
        if tool is None:
            return ToolResult(
                name=tool_call.name,
                output=None,
                tool_call_id=tool_call.id,
                success=False,
                error_message=f"未找到工具: {tool_call.name}",
            )

        try:
            output = tool.run(tool_call.arguments, context)
            return ToolResult(
                name=tool_call.name,
                output=output,
                tool_call_id=tool_call.id,
                success=True,
            )
        except Exception as exc:  # noqa: BLE001 - 这里需要兜底收集工具异常
            return ToolResult(
                name=tool_call.name,
                output=None,
                tool_call_id=tool_call.id,
                success=False,
                error_message=str(exc),
            )

    def _build_tool_calls(self, decision: object, step_index: int) -> list[ToolCall]:
        """把 brain 决策统一转成工具调用列表。"""

        raw_calls = decision.normalized_tool_calls()
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

    def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext,
        on_result: Callable[[ToolCall, ToolResult], None] | None = None,
    ) -> list[tuple[ToolCall, ToolResult]]:
        """执行工具调用列表，对只读工具自动并行。"""

        results: list[tuple[ToolCall, ToolResult]] = []
        parallel_buffer: list[ToolCall] = []

        def flush_parallel_buffer() -> None:
            nonlocal parallel_buffer
            if not parallel_buffer:
                return

            worker_count = min(len(parallel_buffer), 4)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_by_tool_call = {
                    executor.submit(self._execute_tool, tool_call, context): tool_call
                    for tool_call in parallel_buffer
                }
                for future in as_completed(future_by_tool_call):
                    tool_call = future_by_tool_call[future]
                    result = future.result()
                    results.append((tool_call, result))
                    if on_result is not None:
                        on_result(tool_call, result)
            parallel_buffer = []

        for tool_call in tool_calls:
            if self._supports_parallel(tool_call.name):
                parallel_buffer.append(tool_call)
                continue

            flush_parallel_buffer()
            result = self._execute_tool(tool_call, context)
            results.append((tool_call, result))
            if on_result is not None:
                on_result(tool_call, result)

        flush_parallel_buffer()
        return results

    def _supports_parallel(self, tool_name: str) -> bool:
        """判断工具是否适合并行执行。"""

        tool = self.tools.get(tool_name)
        return bool(tool is not None and getattr(tool, "supports_parallel", False))

    def _build_confirmation_pause_response(
        self,
        state: AgentState,
        steps: list[StepRecord],
        turn_index: int,
        step_index: int,
        tool_calls: list[ToolCall],
        tool_results: list[ToolResult],
        on_event: Callable[[AgentEvent], None] | None,
    ) -> AgentResponse | None:
        for tool_call, tool_result in zip(tool_calls, tool_results):
            if not self._requires_user_confirmation(tool_result):
                continue

            response = AgentResponse(
                task=state.current_input,
                final_output="",
                steps=steps,
            )
            return response

        return None

    def _requires_user_confirmation(self, tool_result: ToolResult) -> bool:
        return bool(
            tool_result.success
            and isinstance(tool_result.output, dict)
            and tool_result.output.get("requires_confirmation") is True
        )

    def _emit_event(
        self,
        on_event: Callable[[AgentEvent], None] | None,
        event: AgentEvent,
    ) -> None:
        """把实时事件发送给外部观察者。"""

        if on_event is not None:
            on_event(event)

    def _is_cancelled(self, context: ToolContext) -> bool:
        cancel_event = context.metadata.get("cancel_event")
        return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())

    def _build_cancelled_response(
        self,
        state: AgentState,
        steps: list[StepRecord],
        history_steps: list[StepRecord],
        turn_index: int,
        step_index: int,
        on_event: Callable[[AgentEvent], None] | None,
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
        self._emit_event(
            on_event,
            AgentEvent(
                type="final",
                step_index=step_index,
                message="当前任务已停止。",
                final_answer=final_output,
            ),
        )
        self._emit_event(
            on_event,
            AgentEvent(
                type="turn_finished",
                step_index=step_index,
                message="本轮处理已停止。",
                final_answer=final_output,
            ),
        )
        return response

    def _build_limit_response(
        self,
        state: AgentState,
        steps: list[StepRecord],
        history_steps: list[StepRecord],
        turn_index: int,
        step_index: int,
        on_event: Callable[[AgentEvent], None] | None,
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
        self._emit_event(
            on_event,
            AgentEvent(
                type="limit_reached",
                step_index=step_index,
                message="已达到单轮安全步数上限。",
                final_answer=final_output,
            ),
        )
        self._emit_event(
            on_event,
            AgentEvent(
                type="turn_finished",
                step_index=step_index,
                message="本轮处理结束，但模型没有自然收敛。",
                final_answer=response.final_output,
            ),
        )
        return response
