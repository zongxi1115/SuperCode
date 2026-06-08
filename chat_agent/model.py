from __future__ import annotations

from typing import Any

from agent.openai_model import OpenAICompatibleModel
from agent.schema import AgentState, ConversationMessage


class ChatPromptModel(OpenAICompatibleModel):
    """Model adapter for plain API chat without tools."""

    def _build_messages(
        self,
        state: AgentState,
        tool_definitions: dict[str, dict[str, Any]],
        response_mode: str = "legacy_json",
    ) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = [
            {
                "role": "system",
                "content": (
                    "你是 SuperCode 的 Chat 智能体，只负责普通对话和直接回答问题。"
                    "不要调用工具、不要读取文件、不要执行命令、不要声称已经检查本地代码。"
                    "如果用户明确要求改代码、调研项目、制定计划或部署，请建议切换到对应模式。"
                ),
            }
        ]
        previous_messages, latest_user_message = self._split_latest_user_message(state)
        messages.extend(self._conversation_messages_for_model(previous_messages))
        if latest_user_message:
            messages.append({"role": "user", "content": latest_user_message})
        return messages

    def _split_latest_user_message(self, state: AgentState) -> tuple[list[ConversationMessage], str]:
        messages = list(state.conversation_messages)
        current_input = state.current_input.strip()
        if not messages:
            return [], current_input

        last_message = messages[-1]
        if (
            last_message.role == "user"
            and current_input
            and str(last_message.content or "").strip() == current_input
        ):
            return messages[:-1], str(last_message.content or "").strip()
        return messages, current_input

    def _conversation_messages_for_model(
        self,
        messages: list[ConversationMessage],
        limit: int = 20,
    ) -> list[dict[str, object]]:
        rendered: list[dict[str, object]] = []
        for message in messages[-limit:]:
            role = "assistant" if message.role == "assistant" else "user"
            content = str(message.content or "").strip()
            if content:
                rendered.append({"role": role, "content": content})
        return rendered
