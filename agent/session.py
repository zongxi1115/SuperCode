from __future__ import annotations

from dataclasses import dataclass, field
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

        self.state.conversation_messages.append(
            ConversationMessage(role="assistant", content=response.final_output)
        )
        self.turns.append(
            ConversationTurn(
                user_message=cleaned_message,
                assistant_message=response.final_output,
                response=response,
            )
        )
        return response

    def clear(self) -> None:
        """清空会话上下文。"""

        self.state = AgentState(task=self.task)
        self.turns.clear()

    def history_as_text(self) -> str:
        """把历史消息转成纯文本，便于调试。"""

        if not self.state.conversation_messages:
            return "暂无会话历史。"

        lines: list[str] = []
        for message in self.state.conversation_messages:
            role_name = "用户" if message.role == "user" else "助手"
            lines.append(f"{role_name}: {message.content}")
        return "\n".join(lines)
