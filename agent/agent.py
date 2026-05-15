from __future__ import annotations

from pathlib import Path
from typing import Callable

from .brain import AgentBrain
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

        steps: list[StepRecord] = []
        state.tool_results = []
        state.data["step_records"] = steps
        tool_descriptions = {name: tool.description for name, tool in self.tools.items()}
        context = ToolContext(workspace=self.workspace)
        self._emit_event(
            on_event,
            AgentEvent(
                type="turn_started",
                message=f"开始处理本轮请求：{state.current_input}",
            ),
        )

        for index in range(1, self.max_steps + 1):
            decision = self.brain.decide(state=state, tool_descriptions=tool_descriptions)
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
                steps.append(
                    StepRecord(
                        index=index,
                        thought=decision.thought,
                        final_answer=decision.final_answer,
                    )
                )
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

            tool_call = ToolCall(
                name=decision.tool_name,
                arguments=decision.tool_arguments,
            )
            self._emit_event(
                on_event,
                AgentEvent(
                    type="tool_call",
                    step_index=index,
                    message=f"第 {index} 步准备调用工具 {tool_call.name}。",
                    thought=decision.thought,
                    tool_call=tool_call,
                ),
            )
            result = self._execute_tool(tool_call, context)
            state.add_tool_result(result)
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

            steps.append(
                StepRecord(
                    index=index,
                    thought=decision.thought,
                    tool_call=tool_call,
                    tool_result=result,
                )
            )

        final_output = f"任务在 {self.max_steps} 步内未完成，请调整 brain 或增大 max_steps。"
        steps.append(
            StepRecord(
                index=self.max_steps + 1,
                thought="已达到最大步数限制，停止执行。",
                final_answer=final_output,
            )
        )
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
                success=False,
                error_message=f"未找到工具: {tool_call.name}",
            )

        try:
            output = tool.run(tool_call.arguments, context)
            return ToolResult(name=tool_call.name, output=output, success=True)
        except Exception as exc:  # noqa: BLE001 - 这里需要兜底收集工具异常
            return ToolResult(
                name=tool_call.name,
                output=None,
                success=False,
                error_message=str(exc),
            )

    def _emit_event(
        self,
        on_event: Callable[[AgentEvent], None] | None,
        event: AgentEvent,
    ) -> None:
        """把实时事件发送给外部观察者。"""

        if on_event is not None:
            on_event(event)
