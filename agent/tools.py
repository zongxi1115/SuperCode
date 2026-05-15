from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolContext:
    """工具执行上下文。"""

    workspace: Path


class BaseTool(ABC):
    """工具基类。"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        """执行工具逻辑并返回结果。"""

    def _resolve_path(self, raw_path: str, context: ToolContext) -> Path:
        """把相对路径解析到工作区内，并阻止越界访问。"""

        workspace = context.workspace.resolve()
        candidate = (workspace / raw_path).resolve()
        if workspace != candidate and workspace not in candidate.parents:
            raise ValueError(f"路径越界，不允许访问工作区外部: {raw_path}")
        return candidate


class ListFilesTool(BaseTool):
    """列出目录中的文件。"""

    name = "list_files"
    description = "列出指定目录下的文件和子目录，适合先摸清项目结构。"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> list[str]:
        relative_path = str(arguments.get("path", "."))
        target = self._resolve_path(relative_path, context)
        if not target.exists():
            raise FileNotFoundError(f"目录不存在: {relative_path}")
        if not target.is_dir():
            raise NotADirectoryError(f"目标不是目录: {relative_path}")

        items: list[str] = []
        for child in sorted(target.rglob("*")):
            if child.is_dir():
                continue
            items.append(str(child.relative_to(context.workspace)).replace("\\", "/"))
        return items


class ReadFileTool(BaseTool):
    """读取文本文件内容。"""

    name = "read_file"
    description = "读取一个文本文件的内容，适合分析 README、源码和配置文件。"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        relative_path = str(arguments["path"])
        encoding = str(arguments.get("encoding", "utf-8"))
        target = self._resolve_path(relative_path, context)
        if not target.exists():
            raise FileNotFoundError(f"文件不存在: {relative_path}")
        if not target.is_file():
            raise IsADirectoryError(f"目标不是文件: {relative_path}")
        return target.read_text(encoding=encoding)


class WriteFileTool(BaseTool):
    """写入文本文件内容。"""

    name = "write_file"
    description = "把文本内容写入文件，适合生成分析报告、代码草稿或说明文档。"

    def run(self, arguments: dict[str, Any], context: ToolContext) -> str:
        relative_path = str(arguments["path"])
        content = str(arguments.get("content", ""))
        encoding = str(arguments.get("encoding", "utf-8"))

        target = self._resolve_path(relative_path, context)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        return f"已写入 {target.relative_to(context.workspace)}"
