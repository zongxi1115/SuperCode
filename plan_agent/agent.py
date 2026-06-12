from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.llm_client import OpenAICompatibleClient
from zonix import Agent, agent as build_zonix_agent
from zonix.tools import ToolDefinition

from .model import PlanPromptModel
from .registry import build_plan_tools


def _tool_definitions(tools: list[ToolDefinition]) -> dict[str, dict[str, object]]:
    return {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.input_schema(),
        }
        for tool in tools
    }


def build_plan_agent(
    client: OpenAICompatibleClient,
    *,
    workspace: str | Path,
    tools: list[ToolDefinition] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    resolved_tools = tools if tools is not None else build_plan_tools()
    model = PlanPromptModel(client, workspace=workspace)
    agent = build_zonix_agent(
        "plan",
        role="SuperCode planning agent",
        model=model,
    )
    agent.prompt(model._build_base_prompt())
    agent.prompt(model._build_system_info())
    agent.prompt(lambda _ctx, _task: model.build_tool_registry_prompt(_tool_definitions(agent.tools)))
    agent.prompt(model.build_native_protocol_prompt())
    agent.prompt(model.build_runtime_context_prompt)
    agent.use(*resolved_tools)
    agent.workspace = Path(workspace).resolve()
    agent.tool_context_metadata = dict(metadata or {})
    return agent
