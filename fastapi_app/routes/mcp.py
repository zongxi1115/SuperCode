from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from fastapi_app.api_models import MCPServerTestRequest, MCPServersPayload
from fastapi_app.mcp.client import list_mcp_tools
from fastapi_app.mcp.config_store import (
    load_mcp_servers,
    load_mcp_servers_with_status,
    mcp_servers_store_path,
    normalize_mcp_server,
    save_mcp_servers,
    set_mcp_server_status,
)


@dataclass(frozen=True)
class MCPRouteDeps:
    app_data_root: Path


def register_mcp_routes(app: FastAPI, *, deps: MCPRouteDeps) -> None:
    @app.get("/api/mcp/servers")
    async def get_mcp_servers() -> JSONResponse:
        return JSONResponse(
            {
                "servers": load_mcp_servers_with_status(deps.app_data_root),
                "configPath": str(mcp_servers_store_path(deps.app_data_root)),
            }
        )

    @app.put("/api/mcp/servers")
    async def update_mcp_servers(payload: MCPServersPayload) -> JSONResponse:
        servers = save_mcp_servers(
            deps.app_data_root,
            [server.model_dump(exclude_none=True) for server in payload.servers],
        )
        return JSONResponse(
            {
                "servers": load_mcp_servers_with_status(deps.app_data_root),
                "configPath": str(mcp_servers_store_path(deps.app_data_root)),
            }
        )

    @app.post("/api/mcp/servers/{server_id}/test")
    async def test_mcp_server(server_id: str, payload: MCPServerTestRequest | None = None) -> JSONResponse:
        server: dict[str, Any] | None = None
        if payload is not None and payload.server is not None:
            server = normalize_mcp_server(payload.server.model_dump(exclude_none=True))
        else:
            server = next(
                (item for item in load_mcp_servers(deps.app_data_root) if str(item.get("id")) == server_id),
                None,
            )
        if server is None:
            raise HTTPException(status_code=404, detail="未找到 MCP server 配置。")
        server["id"] = server_id or str(server.get("id") or "")

        try:
            tools = await asyncio.to_thread(list_mcp_tools, server)
        except Exception as exc:  # noqa: BLE001 - surface protocol/setup failures to UI
            set_mcp_server_status(
                str(server.get("id") or server_id),
                state="error",
                message=str(exc),
                tool_count=0,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        summaries = [
            {
                "name": str(tool.get("name") or ""),
                "description": str(tool.get("description") or ""),
                "parametersSchema": tool.get("parameters_schema") or {"type": "object", "properties": {}},
            }
            for tool in tools
        ]
        set_mcp_server_status(
            str(server.get("id") or server_id),
            state="ok",
            message=f"已发现 {len(summaries)} 个工具",
            tool_count=len(summaries),
        )
        return JSONResponse({"toolCount": len(summaries), "tools": summaries})
