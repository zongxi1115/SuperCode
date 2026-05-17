from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable

from .schema import AgentEvent, AgentResponse, AgentState, ConversationMessage


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
        tool_summary = self._build_tool_summary(response)
        if tool_summary:
            self.state.conversation_messages.append(
                ConversationMessage(role="system", content=tool_summary)
            )
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
        tool_summary = self._build_tool_summary(response)
        if tool_summary:
            self.state.conversation_messages.append(
                ConversationMessage(role="system", content=tool_summary)
            )
        return response

    def clear(self) -> None:
        """清空会话上下文。"""

        self.state = AgentState(task=self.task)
        self.turns.clear()

    def _build_tool_summary(self, response: AgentResponse) -> str:
        tool_steps = [
            step
            for step in response.steps
            if step.tool_call is not None or step.tool_calls or step.tool_result is not None or step.tool_results
        ]
        if not tool_steps:
            return ""

        lines = ["[内部工具轨迹摘要] 以下内容供后续轮次复用，不是新的用户消息。"]
        for step in tool_steps:
            step_prefix = f"第 {step.turn_index} 轮 步骤 {step.index}"
            tool_calls = step.tool_calls or ([step.tool_call] if step.tool_call is not None else [])
            tool_results = step.tool_results or ([step.tool_result] if step.tool_result is not None else [])

            if self._include_thoughts_in_context() and step.thought:
                lines.append(f"{step_prefix} 思考：{step.thought}")

            for tool_call in tool_calls:
                lines.append(
                    f"{step_prefix} 工具调用：{tool_call.name} "
                    f"{json.dumps(tool_call.arguments, ensure_ascii=False)}"
                )

            for tool_result in tool_results:
                if tool_result is None:
                    continue
                lines.append(f"{step_prefix} 工具是否成功：{tool_result.success}")
                if tool_result.success:
                    output_text = (
                        tool_result.output
                        if isinstance(tool_result.output, str)
                        else json.dumps(tool_result.output, ensure_ascii=False)
                    )
                    lines.append(f"{step_prefix} 工具输出：{output_text.strip()}")
                else:
                    lines.append(f"{step_prefix} 工具错误：{tool_result.error_message}")

        return "\n".join(lines)

    def _include_thoughts_in_context(self) -> bool:
        metadata = getattr(self.agent, "tool_context_metadata", {})
        if not isinstance(metadata, dict):
            return False
        return bool(metadata.get("include_thoughts_in_context"))

    def history_as_text(self) -> str:
        """把历史消息转成纯文本，便于调试。"""

        if not self.state.conversation_messages:
            return "暂无会话历史。"

        lines: list[str] = []
        for message in self.state.conversation_messages:
            role_name = "用户" if message.role == "user" else "助手"
            lines.append(f"{role_name}: {message.content}")
        return "\n".join(lines)
