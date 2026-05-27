from __future__ import annotations

from typing import Callable

from .schema import AgentEvent, ToolCall, ToolResult


class AgentEventEmitter:
    """Small wrapper around the optional runtime event callback."""

    def __init__(self, on_event: Callable[[AgentEvent], None] | None) -> None:
        self.on_event = on_event

    def emit(self, event: AgentEvent) -> None:
        if self.on_event is not None:
            self.on_event(event)


def turn_started(current_input: str) -> AgentEvent:
    return AgentEvent(
        type="turn_started",
        message=f"开始处理本轮请求：{current_input}",
    )


def thought_delta(step_index: int, thought: str, delta: str) -> AgentEvent:
    return AgentEvent(
        type="thought_delta",
        step_index=step_index,
        message=f"第 {step_index} 步正在流式输出思考。",
        thought=thought,
        delta=delta,
    )


def tool_input_started(step_index: int, tool_call: ToolCall) -> AgentEvent:
    return AgentEvent(
        type="tool_input_started",
        step_index=step_index,
        message=f"第 {step_index} 步开始流式生成工具 {tool_call.name} 的输入。",
        tool_call=tool_call,
    )


def tool_input_delta(step_index: int, tool_call: ToolCall, delta: str) -> AgentEvent:
    return AgentEvent(
        type="tool_input_delta",
        step_index=step_index,
        message=f"第 {step_index} 步正在流式生成工具 {tool_call.name} 的输入。",
        tool_call=tool_call,
        delta=delta,
    )


def final_answer_delta(
    step_index: int,
    thought: str | None,
    final_answer: str,
    delta: str,
) -> AgentEvent:
    return AgentEvent(
        type="final_answer_delta",
        step_index=step_index,
        message=f"第 {step_index} 步正在流式输出最终答复。",
        thought=thought,
        final_answer=final_answer,
        delta=delta,
    )


def usage(step_index: int, latest_usage: dict[str, int]) -> AgentEvent:
    return AgentEvent(
        type="usage",
        step_index=step_index,
        message=f"第 {step_index} 步已更新模型 usage。",
        usage=latest_usage,
    )


def thought(step_index: int, value: str) -> AgentEvent:
    return AgentEvent(
        type="thought",
        step_index=step_index,
        message=f"第 {step_index} 步正在思考。",
        thought=value,
    )


def tool_call_started(
    step_index: int,
    step_thought: str,
    tool_call: ToolCall,
    parallel: bool,
) -> AgentEvent:
    return AgentEvent(
        type="tool_call",
        step_index=step_index,
        message=(
            f"第 {step_index} 步准备并行调用工具 {tool_call.name}。"
            if parallel
            else f"第 {step_index} 步准备调用工具 {tool_call.name}。"
        ),
        thought=step_thought,
        tool_call=tool_call,
    )


def tool_result_ready(
    step_index: int,
    tool_call: ToolCall,
    tool_result: ToolResult,
) -> AgentEvent:
    return AgentEvent(
        type="tool_result",
        step_index=step_index,
        message=f"第 {step_index} 步工具 {tool_call.name} 已返回结果。",
        tool_call=tool_call,
        tool_result=tool_result,
    )


def final(step_index: int, thought_value: str, final_answer: str | None) -> AgentEvent:
    return AgentEvent(
        type="final",
        step_index=step_index,
        message="本轮已得到最终答案。",
        thought=thought_value,
        final_answer=final_answer,
    )


def turn_finished(step_index: int, final_answer: str, message: str = "本轮处理完成。") -> AgentEvent:
    return AgentEvent(
        type="turn_finished",
        step_index=step_index,
        message=message,
        final_answer=final_answer,
    )


def limit_reached(step_index: int, final_answer: str) -> AgentEvent:
    return AgentEvent(
        type="limit_reached",
        step_index=step_index,
        message="已达到单轮安全步数上限。",
        final_answer=final_answer,
    )


__all__ = [
    "AgentEventEmitter",
    "final",
    "final_answer_delta",
    "limit_reached",
    "thought",
    "thought_delta",
    "tool_call_started",
    "tool_input_delta",
    "tool_input_started",
    "tool_result_ready",
    "turn_finished",
    "turn_started",
    "usage",
]
