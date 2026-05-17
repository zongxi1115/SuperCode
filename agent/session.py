from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .schema import (
    AgentEvent,
    AgentResponse,
    AgentState,
    ConversationMessage,
    StepRecord,
    ToolCall,
    ToolResult,
)


MAX_STORED_TOOL_RECORDS = 80
MAX_STORED_PLANNING_RECORDS = 80
MAX_PLANNING_RECORD_CHARS = 1_200


@dataclass(slots=True)
class ConversationTurn:
    """记录一轮完整对话。"""

    user_message: str
    assistant_message: str
    response: AgentResponse


@dataclass(slots=True)
class ChatSession:
    """多轮对话会话。

    这个对象负责保存用户和助手的历史消息，
    让智能体支持连续提问、追问和上下文记忆。
    """

    agent: object
    task: str = "你是一个可以帮助用户理解和修改项目的编码智能体。"
    state: AgentState = field(init=False)
    turns: list[ConversationTurn] = field(default_factory=list)

    def __post_init__(self) -> None:
        """初始化会话状态。"""

        self.state = AgentState(task=self.task)

    def ask(
        self,
        user_message: str,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
        """向智能体发送一条用户消息，并保留上下文。"""

        cleaned_message = user_message.strip()
        if not cleaned_message:
            raise ValueError("用户消息不能为空。")

        self.state.current_input = cleaned_message
        self.state.conversation_messages.append(
            ConversationMessage(role="user", content=cleaned_message)
        )

        response = self.agent.run_turn(self.state, on_event=on_event)

        if response.final_output.strip():
            self.state.conversation_messages.append(
                ConversationMessage(role="assistant", content=response.final_output)
            )
        self._append_execution_records(response)
        if response.final_output.strip():
            self.turns.append(
                ConversationTurn(
                    user_message=cleaned_message,
                    assistant_message=response.final_output,
                    response=response,
                )
            )
        return response

    def continue_turn(
        self,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> AgentResponse:
        """在不新增用户消息的情况下继续当前任务。"""

        response = self.agent.run_turn(
            self.state,
            on_event=on_event,
            continue_existing_turn=True,
        )

        if response.final_output.strip():
            self.state.conversation_messages.append(
                ConversationMessage(role="assistant", content=response.final_output)
            )
        self._append_execution_records(response)
        return response

    def clear(self) -> None:
        """清空会话上下文。"""

        self.state = AgentState(task=self.task)
        self.turns.clear()

    def _append_execution_records(self, response: AgentResponse) -> None:
        self._append_tool_records(response)
        self._append_planning_records(response)

    def _append_tool_records(self, response: AgentResponse) -> None:
        """把工具调用事实追加到模型上下文账本，不伪装成对话消息。"""

        next_records = list(self.state.data.get("tool_records", []))
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
        name = tool_call.name if tool_call is not None else (tool_result.name if tool_result is not None else "")
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
        """把每一步已经确定的规划思路留下，避免后续重新推导。"""

        next_records = list(self.state.data.get("planning_records", []))
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

    def history_as_text(self) -> str:
        """把历史消息转成纯文本，便于调试。"""

        if not self.state.conversation_messages:
            return "暂无会话历史。"

        lines: list[str] = []
        for message in self.state.conversation_messages:
            role_name = "用户" if message.role == "user" else "助手"
            lines.append(f"{role_name}: {message.content}")
        return "\n".join(lines)
