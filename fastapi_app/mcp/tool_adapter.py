from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.tools import BaseTool, ToolContext

from .client import call_mcp_tool, list_mcp_tools
from .config_store import load_mcp_servers, set_mcp_server_status


def _tool_name_part(value: object, *, fallback: str, max_length: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "")).strip("_")
    return (cleaned or fallback)[:max_length]


def _adapter_tool_name(server_id: str, tool_name: str) -> str:
    server_part = _tool_name_part(server_id, fallback="server", max_length=18)
    tool_part = _tool_name_part(tool_name, fallback="tool", max_length=36)
    return f"mcp__{server_part}__{tool_part}"


class MCPToolAdapter(BaseTool):
    supports_parallel = False

    def __init__(
        self,
        *,
        server: dict[str, Any],
        original_tool_name: str,
        adapter_name: str,
        description: str,
        parameters_schema: dict[str, Any],
    ) -> None:
        self.server = server
        self.original_tool_name = original_tool_name
        self.name = adapter_name
        server_name = str(server.get("name") or server.get("id") or "MCP")
        self.description = f"[MCP:{server_name}] {description or original_tool_name}".strip()
        self.parameters_schema = parameters_schema

    def run(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        return call_mcp_tool(self.server, self.original_tool_name, arguments)


def build_mcp_tools_for_server(server: dict[str, Any], *, seen_names: set[str] | None = None) -> list[BaseTool]:
    server_id = str(server.get("id") or "")
    seen_names = seen_names if seen_names is not None else set()
    tools: list[BaseTool] = []
    discovered_tools = list_mcp_tools(server)
    for tool in discovered_tools:
        original_name = str(tool.get("name") or "").strip()
        if not original_name:
            continue
        adapter_name = _adapter_tool_name(server_id, original_name)
        base_name = adapter_name
        suffix = 2
        while adapter_name in seen_names:
            adapter_name = f"{base_name[:58]}__{suffix}"
            suffix += 1
        seen_names.add(adapter_name)
        tools.append(
            MCPToolAdapter(
                server=server,
                original_tool_name=original_name,
                adapter_name=adapter_name,
                description=str(tool.get("description") or ""),
                parameters_schema=(
                    tool.get("parameters_schema")
                    if isinstance(tool.get("parameters_schema"), dict)
                    else {"type": "object", "properties": {}}
                ),
            )
        )
    set_mcp_server_status(
        server_id,
        state="ok",
        message=f"已发现 {len(tools)} 个工具",
        tool_count=len(tools),
    )
    return tools


def build_enabled_mcp_tools(root: Path) -> list[BaseTool]:
    enabled_servers = [server for server in load_mcp_servers(root) if server.get("enabled")]
    tools: list[BaseTool] = []
    seen_names = {tool.name for tool in tools}
    for server in enabled_servers:
        server_id = str(server.get("id") or "")
        try:
            tools.extend(build_mcp_tools_for_server(server, seen_names=seen_names))
        except Exception as exc:  # noqa: BLE001 - a broken MCP server should not disable the whole agent
            set_mcp_server_status(
                server_id,
                state="error",
                message=str(exc),
                tool_count=0,
            )
    return tools
