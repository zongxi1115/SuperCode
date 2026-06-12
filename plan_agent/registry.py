from __future__ import annotations

from collections.abc import Callable
from typing import Any

from coding_agent.registry import (
    glob_file,
    grep_file,
    list_file,
    read_file,
    remember_preference,
)
from zonix.tools import ToolDefinition

from .tools import (
    ask_plan_questions,
    create_task,
    fetch_url_content,
    get_task_status,
    read_current_plan,
    save_plan,
    search_web,
)


def _tool(func: Callable[..., Any]) -> ToolDefinition:
    return ToolDefinition.from_func(
        func,
        supports_parallel=bool(getattr(func, "supports_parallel", False)),
        catch_errors=True,
    )


def build_plan_tools() -> list[ToolDefinition]:
    return [
        _tool(list_file),
        _tool(remember_preference),
        _tool(glob_file),
        _tool(read_file),
        _tool(grep_file),
        _tool(search_web),
        _tool(fetch_url_content),
        _tool(ask_plan_questions),
        _tool(save_plan),
        _tool(read_current_plan),
        _tool(create_task),
        _tool(get_task_status),
    ]
