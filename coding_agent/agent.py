from __future__ import annotations

from pathlib import Path
from typing import Any

from zonix.tools import ToolDefinition

from agent.llm_client import OpenAICompatibleClient
from zonix import Agent
from zonix import agent as build_zonix_agent

from .model import CodeExplorationPromptModel, CodingPromptModel
from .registry import build_code_exploration_tools, build_coding_tools


def _attach_runtime_metadata(
    agent: Agent,
    *,
    workspace: str | Path,
    metadata: dict[str, Any] | None,
) -> Agent:
    agent.workspace = Path(workspace).resolve()
    agent.tool_context_metadata = dict(metadata or {})
    return agent


def _tool_definitions(tools: list[ToolDefinition]) -> dict[str, dict[str, object]]:
    return {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.input_schema(),
        }
        for tool in tools
    }


def _attach_prompt_chain(
    agent: Agent,
    model: CodingPromptModel,
) -> Agent:
    agent.prompt(model._build_base_prompt())
    agent.prompt(model._build_system_info())
    agent.prompt(lambda _ctx, _task: model.build_tool_registry_prompt(_tool_definitions(agent.tools)))
    agent.prompt(model.build_native_protocol_prompt())
    agent.prompt(model.build_runtime_context_prompt)
    return agent


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
    _attach_prompt_chain(agent, model)
    agent.use(*resolved_tools)
    return _attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)


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
    _attach_prompt_chain(agent, model)
    agent.use(*resolved_tools)
    return _attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)
