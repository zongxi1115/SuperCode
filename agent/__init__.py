"""简单编码智能体框架。

这个包提供一个尽量直白的编码智能体最小实现：

1. `CodingAgent` 负责驱动执行循环。
2. `AgentBrain` 负责决定下一步是调用工具还是直接结束。
3. `BaseTool` 及其子类负责与外部世界交互。

设计目标是先把骨架搭稳，调用保持简单，方便后续替换成真实大模型。
"""

from .agent import CodingAgent
from .brain import AgentBrain, BrainDecision
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
from .tools import BaseTool, ListFilesTool, ReadFileTool, WriteFileTool

__all__ = [
    "AgentBrain",
    "AgentEvent",
    "AgentLLMConfig",
    "AgentResponse",
    "AgentState",
    "BaseTool",
    "BrainDecision",
    "ChatSession",
    "CodingAgent",
    "ConversationMessage",
    "ConversationTurn",
    "ListFilesTool",
    "OpenAICompatibleBrain",
    "OpenAICompatibleClient",
    "ReadFileTool",
    "StepRecord",
    "ToolCall",
    "ToolResult",
    "WriteFileTool",
]
