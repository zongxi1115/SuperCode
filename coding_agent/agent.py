from __future__ import annotations

from pathlib import Path
from typing import Any

from supercode_agent import attach_runtime_metadata, attach_tool_agent_prompts
from zonix.tools import ToolDefinition

from agent.llm_client import OpenAICompatibleClient
from zonix import Agent
from zonix import agent as build_zonix_agent

from .model import CodeExplorationPromptModel, CodingPromptModel
from .registry import build_code_exploration_tools, build_coding_tools


def build_coding_agent(
    client: OpenAICompatibleClient,
    *,
    workspace: str | Path,
    tools: list[ToolDefinition] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    resolved_tools = tools if tools is not None else build_coding_tools()
    model = CodingPromptModel(client, workspace=workspace)
    agent = build_zonix_agent(
        "coding",
        role="SuperCode coding agent",
        model=model,
        recover_tool_input_errors=True,
    )
    attach_tool_agent_prompts(agent, model)
    agent.use(*resolved_tools)
    return attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)


def build_code_exploration_agent(
    client: OpenAICompatibleClient,
    *,
    workspace: str | Path,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    resolved_tools = build_code_exploration_tools()
    model = CodeExplorationPromptModel(client, workspace=workspace)
    agent = build_zonix_agent(
        "code_exploration",
        role="SuperCode read-only code exploration agent",
        model=model,
        recover_tool_input_errors=True,
    )
    attach_tool_agent_prompts(agent, model)
    agent.use(*resolved_tools)
    return attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)
