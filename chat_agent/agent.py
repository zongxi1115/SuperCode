from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.llm_client import OpenAICompatibleClient
from supercode_agent import attach_runtime_metadata
from zonix import Agent, agent as build_zonix_agent

from .model import ChatPromptModel


def build_chat_agent(
    client: OpenAICompatibleClient,
    *,
    workspace: str | Path,
    metadata: dict[str, Any] | None = None,
) -> Agent:
    model = ChatPromptModel(client)
    agent = build_zonix_agent(
        "chat",
        role="SuperCode chat agent",
        model=model,
    )
    for prompt in model.build_prompt_chain():
        if prompt:
            agent.prompt(prompt)
    return attach_runtime_metadata(agent, workspace=workspace, metadata=metadata)
