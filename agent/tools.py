from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolContext:
    """工具执行上下文。

    这里只保留框架级别的最小上下文定义。
    具体工具如何解释路径、如何做安全校验，交给上层具体智能体自己实现。
    """

    workspace: Path
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """工具抽象接口。

    `agent` 框架层只关心：
    1. 工具有名字和说明
    2. 工具能接收参数并返回结果

    至于文件系统操作、命令执行、补丁写入等具体能力，
    不放在框架层里，交给具体场景包自己实现。
    """

    name: str = ""
    description: str = ""
    supports_parallel: bool = False

    @abstractmethod
    def run(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        """执行工具逻辑并返回结果。"""
