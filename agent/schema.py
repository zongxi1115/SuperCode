from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentEvent:
    """记录智能体运行中的实时事件。"""

    type: str
    step_index: int | None = None
    message: str = ""
    delta: str | None = None
    thought: str | None = None
    tool_call: "ToolCall | None" = None
    tool_result: "ToolResult | None" = None
    final_answer: str | None = None
    usage: dict[str, int] | None = None


@dataclass(slots=True)
class ConversationMessage:
    """记录一条对话消息。"""

    role: str
    content: str
    reasoning_content: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ToolCall:
    """记录一次工具调用请求。"""

    name: str
    id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """记录一次工具调用结果。"""

    name: str
    output: Any
    tool_call_id: str | None = None
    success: bool = True
    error_message: str | None = None


@dataclass(slots=True)
class StepRecord:
    """记录智能体每一步的思考、动作和观察结果。"""

    turn_index: int
    index: int
    thought: str
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    final_answer: str | None = None
    provider_response_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AgentState:
    """智能体运行时状态。

    `data` 用于保存 model/runtime 在多轮执行中的中间变量，避免引入复杂链式调用。
    """

    task: str
    current_input: str = ""
    conversation_messages: list[ConversationMessage] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    step_records: list[StepRecord] = field(default_factory=list)
    tool_records: list[dict[str, Any]] = field(default_factory=list)
    planning_records: list[dict[str, Any]] = field(default_factory=list)
    external_records: list[str] = field(default_factory=list)
    turn_index: int = 0
    include_thoughts_in_context: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def start_turn(self, *, continue_existing_turn: bool, include_thoughts: bool) -> int:
        if not continue_existing_turn:
            self.turn_index += 1
        self.include_thoughts_in_context = include_thoughts
        self.tool_results.clear()
        return self.turn_index

    def first_step_index(self, *, continue_existing_turn: bool) -> int:
        if not continue_existing_turn:
            return 1
        indices = [
            step.index
            for step in self.step_records
            if step.turn_index == self.turn_index
        ]
        return max(indices, default=0) + 1

    def add_tool_result(self, result: ToolResult) -> None:
        """把工具结果追加到状态中。"""

        self.tool_results.append(result)

    def latest_tool_result(self) -> ToolResult | None:
        """返回最近一次工具结果。"""

        if not self.tool_results:
            return None
        return self.tool_results[-1]

    def latest_success_result(self, tool_name: str | None = None) -> ToolResult | None:
        """返回最近一次成功结果，可按工具名过滤。"""

        for result in reversed(self.tool_results):
            if not result.success:
                continue
            if tool_name is None or result.name == tool_name:
                return result
        return None


@dataclass(slots=True)
class AgentResponse:
    """智能体最终输出。"""

    task: str
    final_output: str
    steps: list[StepRecord] = field(default_factory=list)
