"""通用智能体框架。

推荐从 `Agent` 进入：它代表“同一个智能体”。
内部再由 model adapter、runtime、tool executor 分别负责模型调用、
执行循环和工具调度。
"""

from .config import AgentLLMConfig
from .core import Agent
from .openai_model import OpenAICompatibleModel
from .llm_client import OpenAICompatibleClient
from .model import ModelAdapter, ModelStep, ModelStreamUpdate
from .schema import (
    AgentEvent,
    AgentResponse,
    AgentState,
    ConversationMessage,
    StepRecord,
    ToolCall,
    ToolResult,
)
from .session import ChatSession, ConversationTurn
from .tooling import ToolExecutor, ToolRegistry
from .tools import BaseTool, ToolContext

__all__ = [
    "Agent",
    "AgentEvent",
    "AgentLLMConfig",
    "AgentResponse",
    "AgentState",
    "BaseTool",
    "ChatSession",
    "ConversationMessage",
    "ConversationTurn",
    "ModelAdapter",
    "ModelStep",
    "ModelStreamUpdate",
    "OpenAICompatibleClient",
    "OpenAICompatibleModel",
    "StepRecord",
    "ToolExecutor",
    "ToolRegistry",
    "ToolContext",
    "ToolCall",
    "ToolResult",
]
