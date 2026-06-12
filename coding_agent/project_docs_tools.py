from __future__ import annotations

from zonix.tools import ToolContext

from fastapi_app.project_docs_store import (
    read_project_docs as read_project_docs_store,
)
from fastapi_app.project_docs_store import (
    write_project_docs as write_project_docs_store,
)


def read_project_docs(ctx: ToolContext) -> dict[str, object]:
    """读取项目文档插件维护的当前工作区项目文档。"""

    return read_project_docs_store(str(ctx.workspace))


def write_project_docs(ctx: ToolContext, markdown: str) -> dict[str, object]:
    """覆盖写入项目文档插件维护的当前工作区项目文档。"""

    return write_project_docs_store(str(ctx.workspace), markdown)


read_project_docs.supports_parallel = True
