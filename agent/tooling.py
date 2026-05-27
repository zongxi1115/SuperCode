from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .schema import ToolCall, ToolResult
from .tools import BaseTool, ToolContext


class ToolRegistry:
    """Named tool collection used by the agent runtime."""

    def __init__(self, tools: list[BaseTool]) -> None:
        self.tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def definitions(self) -> dict[str, dict[str, object]]:
        return {
            name: {
                "description": tool.description,
                "parameters_schema": getattr(tool, "parameters_schema", None),
            }
            for name, tool in self.tools.items()
        }

    def supports_parallel(self, name: str) -> bool:
        tool = self.get(name)
        return bool(tool is not None and getattr(tool, "supports_parallel", False))


class ToolExecutor:
    """Executes tool calls and normalizes tool failures into ToolResult."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute_tool(self, tool_call: ToolCall, context: ToolContext) -> ToolResult:
        if self.is_cancelled(context):
            return ToolResult(
                name=tool_call.name,
                output=None,
                tool_call_id=tool_call.id,
                success=False,
                error_message="当前任务已被用户停止。",
            )

        tool = self.registry.get(tool_call.name)
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
        except Exception as exc:  # noqa: BLE001 - tools should report failures as data
            return ToolResult(
                name=tool_call.name,
                output=None,
                tool_call_id=tool_call.id,
                success=False,
                error_message=str(exc),
            )

    def execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        context: ToolContext,
        on_result: Callable[[ToolCall, ToolResult], None] | None = None,
    ) -> list[tuple[ToolCall, ToolResult]]:
        """Execute calls in order, batching adjacent parallel-safe tools."""

        results: list[tuple[ToolCall, ToolResult]] = []
        parallel_buffer: list[ToolCall] = []

        def flush_parallel_buffer() -> None:
            nonlocal parallel_buffer
            if not parallel_buffer:
                return

            worker_count = min(len(parallel_buffer), 4)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_by_tool_call = {
                    executor.submit(self.execute_tool, tool_call, context): tool_call
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
            if self.registry.supports_parallel(tool_call.name):
                parallel_buffer.append(tool_call)
                continue

            flush_parallel_buffer()
            result = self.execute_tool(tool_call, context)
            results.append((tool_call, result))
            if on_result is not None:
                on_result(tool_call, result)

        flush_parallel_buffer()
        return results

    @staticmethod
    def is_cancelled(context: ToolContext) -> bool:
        cancel_event = context.metadata.get("cancel_event")
        return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())


__all__ = ["ToolExecutor", "ToolRegistry"]
