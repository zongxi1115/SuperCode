"""通用智能体框架。

这个包只保留与“智能体运行机制”相关的通用抽象：

1. `CodingAgent` 负责驱动执行循环
2. `AgentBrain` 负责决策下一步动作
3. `BaseTool` 和 `ToolContext` 只定义工具抽象接口

具体场景下的提示词、工具集合、领域规则，
应由上层业务包自行提供，例如 `coding_agent`。
"""

from .agent import CodingAgent
from .brain import AgentBrain, BrainDecision, BrainStreamingUpdate
from .config import AgentLLMConfig
from .llm_brain import OpenAICompatibleBrain
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
from .session import ChatSession, ConversationTurn
from .tools import BaseTool, ToolContext

__all__ = [
    "AgentBrain",
    "AgentEvent",
    "AgentLLMConfig",
    "AgentResponse",
    "AgentState",
    "BaseTool",
    "BrainDecision",
    "BrainStreamingUpdate",
    "ChatSession",
    "CodingAgent",
    "ConversationMessage",
    "ConversationTurn",
    "OpenAICompatibleBrain",
    "OpenAICompatibleClient",
    "StepRecord",
    "ToolContext",
    "ToolCall",
    "ToolResult",
]
