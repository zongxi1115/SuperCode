from __future__ import annotations

from collections.abc import Callable
from typing import Any

from zonix.tools import ToolDefinition

from .file_tools import (
    apply_patch,
    delete_file,
    glob_file,
    grep_file,
    list_file,
    read_file,
    replace_file,
    write_file,
)
from .git_tools import git_commit, git_log, git_tag
from .planning_tools import create_task, finish_task, get_task_status, read_current_plan
from .project_docs_tools import read_project_docs, write_project_docs
from .subagent_tools import delegate_code_exploration
from .terminal_tools import (
    run_command,
    start_task,
    task_input,
    task_stop,
    task_wait,
)
from .utility_tools import (
    generate_image,
    get_docs,
    load_image_to_conversation,
    open_browser,
    remember_preference,
)


def _tool(func: Callable[..., Any]) -> ToolDefinition:
    return ToolDefinition.from_func(
        func,
        supports_parallel=bool(getattr(func, "supports_parallel", False)),
        catch_errors=True,
    )


def build_coding_tools() -> list[ToolDefinition]:
    """构造编码智能体默认工具集。"""

    return [
        _tool(list_file),
        _tool(remember_preference),
        _tool(generate_image),
        _tool(load_image_to_conversation),
        _tool(get_docs),
        _tool(glob_file),
        _tool(read_file),
        _tool(grep_file),
        _tool(delegate_code_exploration),
        _tool(create_task),
        _tool(get_task_status),
        _tool(finish_task),
        _tool(apply_patch),
        _tool(write_file),
        _tool(replace_file),
        _tool(delete_file),
        _tool(run_command),
        _tool(start_task),
        _tool(task_input),
        _tool(task_wait),
        _tool(task_stop),
        _tool(open_browser),
        _tool(read_current_plan),
        _tool(git_commit),
        _tool(git_log),
        _tool(git_tag),
    ]


def build_project_docs_tools() -> list[ToolDefinition]:
    """构造项目文档插件工具集。"""

    return [_tool(read_project_docs), _tool(write_project_docs)]


def build_code_exploration_tools() -> list[ToolDefinition]:
    """构造代码探索子智能体的只读工具集。"""

    return [
        _tool(list_file),
        _tool(glob_file),
        _tool(read_file),
        _tool(grep_file),
    ]
