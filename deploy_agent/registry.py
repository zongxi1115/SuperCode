from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zonix.tools import ToolDefinition

from .tools import connect, execute, list_files, read_file, transfer_files


def _tool(func: Callable[..., Any]) -> ToolDefinition:
    return ToolDefinition.from_func(
        func,
        supports_parallel=bool(getattr(func, "supports_parallel", False)),
        catch_errors=True,
    )


def build_deploy_tools() -> list[ToolDefinition]:
    """构造部署智能体默认工具集。"""

    return [
        _tool(connect),
        _tool(list_files),
        _tool(read_file),
        _tool(transfer_files),
        _tool(execute),
    ]
