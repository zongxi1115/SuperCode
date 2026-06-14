from __future__ import annotations

from collections.abc import Callable
from typing import Any

from coding_agent import build_coding_tools, build_project_docs_tools
from plan_agent import ask_plan_questions
from plan_agent.tools import fetch_url_content, search_web
from zonix.tools import ToolDefinition

from .tools import ask_user


def _tool(func: Callable[..., Any]) -> ToolDefinition:
    return ToolDefinition.from_func(
        func,
        supports_parallel=bool(getattr(func, "supports_parallel", False)),
        catch_errors=True,
    )


def _dedupe_tools(tools: list[ToolDefinition]) -> list[ToolDefinition]:
    seen: set[str] = set()
    deduped: list[ToolDefinition] = []
    for tool in tools:
        if tool.name in seen:
            continue
        seen.add(tool.name)
        deduped.append(tool)
    return deduped


def build_super_tools() -> list[ToolDefinition]:
    """构造超能模式工具集。"""

    return _dedupe_tools(
        [
            *build_coding_tools(),
            *build_project_docs_tools(),
            _tool(search_web),
            _tool(fetch_url_content),
            _tool(ask_plan_questions),
            _tool(ask_user),
        ]
    )
