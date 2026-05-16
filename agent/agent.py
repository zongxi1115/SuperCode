from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .brain import AgentBrain, BrainStreamingUpdate
from .schema import AgentEvent, AgentResponse, AgentState, StepRecord, ToolCall, ToolResult
from .tools import BaseTool, ToolContext


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
        max_steps: int = 8,
        tool_context_metadata: dict[str, Any] | None = None,
    ) -> None:
        """初始化智能体。

        参数说明：
        - `brain`：负责决定下一步动作的对象
        - `tools`：可供调用的工具列表
        - `workspace`：工具默认操作的工作目录
        - `max_steps`：最大执行步数，避免死循环
        """

        self.brain = brain
        self.workspace = Path(workspace).resolve()
        self.max_steps = max_steps
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
    ) -> AgentResponse:
        """在已有状态上执行当前这一轮。

        这个方法用于多轮对话场景。
        它会保留会话历史，但会清空“本轮工具轨迹”，避免把上一轮工具结果误当成当前轮上下文。
        """

        history_steps = state.data.setdefault("step_records", [])
        turn_index = int(state.data.get("turn_index", 0)) + 1
        state.data["turn_index"] = turn_index
        steps: list[StepRecord] = []
        state.tool_results = []
        tool_descriptions = {name: tool.description for name, tool in self.tools.items()}
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

        for index in range(1, self.max_steps + 1):
            streamed_final_answer = ""
            streamed_thought = ""

            def on_brain_stream(update: BrainStreamingUpdate) -> None:
                nonlocal streamed_final_answer, streamed_thought

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
                tool_descriptions=tool_descriptions,
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

            results = self._execute_tool_calls(tool_calls, context)
            tool_results: list[ToolResult] = []
            for tool_call, result in results:
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

        final_output = f"任务在 {self.max_steps} 步内未完成，请调整 brain 或增大 max_steps。"
        step_record = StepRecord(
            turn_index=turn_index,
            index=self.max_steps + 1,
            thought="已达到最大步数限制，停止执行。",
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
                step_index=self.max_steps + 1,
                message="已达到最大步数限制。",
                final_answer=final_output,
            ),
        )
        self._emit_event(
            on_event,
            AgentEvent(
                type="turn_finished",
                step_index=self.max_steps + 1,
                message="本轮处理结束，但未在限制步数内完成。",
                final_answer=response.final_output,
            ),
        )
        return response

    def _execute_tool(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        """执行单个工具调用，并把异常包装成统一结果。"""

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
                future_results = [
                    executor.submit(self._execute_tool, tool_call, context)
                    for tool_call in parallel_buffer
                ]
                for tool_call, future in zip(parallel_buffer, future_results, strict=True):
                    results.append((tool_call, future.result()))
            parallel_buffer = []

        for tool_call in tool_calls:
            if self._supports_parallel(tool_call.name):
                parallel_buffer.append(tool_call)
                continue

            flush_parallel_buffer()
            results.append((tool_call, self._execute_tool(tool_call, context)))

        flush_parallel_buffer()
        return results

    def _supports_parallel(self, tool_name: str) -> bool:
        """判断工具是否适合并行执行。"""

        tool = self.tools.get(tool_name)
        return bool(tool is not None and getattr(tool, "supports_parallel", False))

    def _emit_event(
        self,
        on_event: Callable[[AgentEvent], None] | None,
        event: AgentEvent,
    ) -> None:
        """把实时事件发送给外部观察者。"""

        if on_event is not None:
            on_event(event)
