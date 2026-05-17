"""编码智能体专用包。

这里放与“编码任务”强相关的内容：

1. 编码提示词
2. 编码场景专用 brain
3. 文件读写、搜索、命令执行等工具实现
"""

from .brain import CodingPromptBrain
from .tools import (
    ExcecuteTool,
    ExecuteTool,
    GitCommitTool,
    GitLogTool,
    GitTagTool,
    GreepToolCompat,
    GrepFileTool,
    InteractiveCommandSession,
    ListFileTool,
    OpenBrowserTool,
    ReadFileTool,
    ReplaceFileTool,
    TerminalInputTool,
    TerminalWaitTool,
    WriteFileTool,
    build_coding_tools,
    execute_git_commit,
    execute_git_tag,
    init_git_repo,
)

__all__ = [
    "CodingPromptBrain",
    "ExcecuteTool",
    "ExecuteTool",
    "GitCommitTool",
    "GitLogTool",
    "GitTagTool",
    "GreepToolCompat",
    "GrepFileTool",
    "InteractiveCommandSession",
    "ListFileTool",
    "OpenBrowserTool",
    "ReadFileTool",
    "ReplaceFileTool",
    "TerminalInputTool",
    "TerminalWaitTool",
    "WriteFileTool",
    "build_coding_tools",
    "execute_git_commit",
    "execute_git_tag",
    "init_git_repo",
]
