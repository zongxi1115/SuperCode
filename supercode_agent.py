from __future__ import annotations

from pathlib import Path
from typing import Any

from zonix import Agent


def attach_runtime_metadata(
    agent: Agent,
    *,
    workspace: str | Path,
    metadata: dict[str, Any] | None,
) -> Agent:
    agent.workspace = Path(workspace).resolve()
    agent.tool_context_metadata = dict(metadata or {})
    return agent


def attach_tool_agent_prompts(agent: Agent, model: Any) -> Agent:
    agent.prompt(model._build_base_prompt())
    agent.prompt(model._build_system_info())
    agent.prompt(
        lambda _ctx, _task: model.build_tool_registry_prompt(
            {
                tool.name: {
                    "description": tool.description,
                    "input_schema": tool.input_schema(),
                }
                for tool in agent.tools
            }
        )
    )
    agent.prompt(model.build_native_protocol_prompt())
    agent.prompt(model.build_runtime_context_prompt)
    return agent
