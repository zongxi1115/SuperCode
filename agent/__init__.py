"""通用智能体框架。

这里保留 SuperCode 后端仍在使用的 LLM client、模型适配器和前端事件账本类型。
智能体编排、工具调度和运行循环由 zonix 提供。
"""

from .config import AgentLLMConfig
from .openai_model import OpenAICompatibleModel
from .llm_client import OpenAICompatibleClient
from .schema import (
    AgentEvent,
    AgentResponse,
    AgentState,
    ConversationMessage,
    StepRecord,
    ToolCall,
    ToolResult,
)

__all__ = [
    "AgentEvent",
    "AgentLLMConfig",
    "AgentResponse",
    "AgentState",
    "ConversationMessage",
    "OpenAICompatibleClient",
    "OpenAICompatibleModel",
    "StepRecord",
    "ToolCall",
    "ToolResult",
]
