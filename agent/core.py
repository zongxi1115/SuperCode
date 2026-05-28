from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .model import ModelAdapter
from .runtime import AgentRuntime
from .schema import AgentEvent, AgentResponse, AgentState, ToolCall, ToolResult
from .tooling import ToolExecutor, ToolRegistry
from .tools import BaseTool, ToolContext


class Agent:
    """Main public agent facade.

    The agent reads as one actor from the outside. Internally it delegates to:
    - a model adapter for the next model step
    - a tool registry/executor for tool calls
    - a runtime for the loop
    """

    def __init__(
        self,
        model: ModelAdapter | object,
        tools: list[BaseTool] | None = None,
        workspace: str | Path = ".",
        max_steps: int | None = None,
        tool_context_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self.workspace = Path(workspace).resolve()
        self.max_steps = max(1, max_steps) if max_steps is not None else None
        self.tool_context_metadata = tool_context_metadata or {}
        self.tool_registry = ToolRegistry(tools or [])
        self.tool_executor = ToolExecutor(self.tool_registry)
        self.runtime = AgentRuntime(
            model=self.model,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            workspace=self.workspace,
            max_steps=self.max_steps,
            tool_context_metadata=self.tool_context_metadata,
        )

    @property
    def tools(self) -> dict[str, BaseTool]:
        """Registered tools keyed by tool name."""

        return self.tool_registry.tools

    def run(
        self,
        task: str,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
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
        return self.runtime.run_turn(
            state,
            on_event=on_event,
            continue_existing_turn=continue_existing_turn,
        )

    def _execute_tool(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        return self.tool_executor.execute_tool(tool_call, context)

    def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext,
        on_result: Callable[[ToolCall, ToolResult], None] | None = None,
    ) -> list[tuple[ToolCall, ToolResult]]:
        return self.tool_executor.execute_tool_calls(
            tool_calls,
            context,
            on_result=on_result,
        )

    def _build_tool_calls(self, step: object, step_index: int) -> list[ToolCall]:
        return self.runtime.build_tool_calls(step, step_index)

    def _supports_parallel(self, tool_name: str) -> bool:
        return self.tool_registry.supports_parallel(tool_name)

    def _requires_user_confirmation(self, tool_result: ToolResult) -> bool:
        return self.runtime.requires_user_confirmation(tool_result)

    def _emit_event(
        self,
        on_event: Callable[[AgentEvent], None] | None,
        event: AgentEvent,
    ) -> None:
        if on_event is not None:
            on_event(event)

    def _is_cancelled(self, context: ToolContext) -> bool:
        return self.tool_executor.is_cancelled(context)

__all__ = ["Agent"]
