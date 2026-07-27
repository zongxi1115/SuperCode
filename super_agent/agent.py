from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.llm_client import OpenAICompatibleClient
from supercode_agent import attach_runtime_metadata, attach_tool_agent_prompts
from zonix import Agent
from zonix import agent as build_zonix_agent
from zonix.tools import ToolDefinition

from .model import SuperPromptModel
from .registry import build_super_tools


def build_super_agent(
    client: OpenAICompatibleClient,
    *,
    workspace: str | Path,
    tools: list[ToolDefinition] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    resolved_tools = tools if tools is not None else build_super_tools()
    model = SuperPromptModel(client, workspace=workspace)
    agent = build_zonix_agent(
        "super",
        role="SuperCode super mode agent",
        model=model,
        recover_tool_input_errors=True,
    )
    attach_tool_agent_prompts(agent, model)
    agent.use(*resolved_tools)
    return attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)
