from __future__ import annotations

from agent.openai_model import OpenAICompatibleModel


class ChatPromptModel(OpenAICompatibleModel):
    """Model adapter for plain API chat without tools."""

    def build_prompt_chain(self) -> list[str]:
        return [
            (
                "你是 SuperCode 的 Chat 智能体，只负责普通对话和直接回答问题。"
                "不要调用工具、不要读取文件、不要执行命令、不要声称已经检查本地代码。"
                "如果用户明确要求改代码、调研项目、制定计划或部署，请建议切换到对应模式。"
            )
        ]
