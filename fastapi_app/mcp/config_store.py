from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_DIRECTORY_NAME = ".supercode"
MCP_SERVERS_FILE_NAME = "mcp_servers.json"
MCP_TRANSPORTS = {"stdio", "streamable_http"}

_SERVER_STATUS: dict[str, dict[str, Any]] = {}


def mcp_servers_store_path(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME / MCP_SERVERS_FILE_NAME


def _clean_string(value: object) -> str:
    return str(value or "").strip()


def _clean_id(value: object) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", _clean_string(value)).strip("-_")
    return cleaned[:80] or uuid.uuid4().hex


def _clean_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_string(item) for item in value if _clean_string(item)]


def _clean_string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, raw_value in value.items():
        key_text = _clean_string(key)
        if not key_text:
            continue
        cleaned[key_text] = str(raw_value or "")
    return cleaned


def normalize_mcp_server(payload: dict[str, Any]) -> dict[str, Any]:
    server_id = _clean_id(payload.get("id"))
    transport = _clean_string(payload.get("transport")) or "stdio"
    if transport not in MCP_TRANSPORTS:
        transport = "stdio"
    return {
        "id": server_id,
        "name": _clean_string(payload.get("name")) or server_id,
        "enabled": bool(payload.get("enabled", True)),
        "transport": transport,
        "command": _clean_string(payload.get("command")),
        "args": _clean_string_list(payload.get("args")),
        "env": _clean_string_map(payload.get("env")),
        "url": _clean_string(payload.get("url")),
        "bearerToken": _clean_string(payload.get("bearerToken")),
        "headers": _clean_string_map(payload.get("headers")),
    }


def normalize_mcp_servers(payload: object) -> list[dict[str, Any]]:
    raw_servers = payload if isinstance(payload, list) else []
    servers: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_server in raw_servers:
        if not isinstance(raw_server, dict):
            continue
        server = normalize_mcp_server(raw_server)
        base_id = server["id"]
        next_id = base_id
        suffix = 2
        while next_id in seen_ids:
            next_id = f"{base_id}-{suffix}"
            suffix += 1
        server["id"] = next_id
        seen_ids.add(next_id)
        servers.append(server)
    return servers


def load_mcp_servers(root: Path) -> list[dict[str, Any]]:
    path = mcp_servers_store_path(root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, dict):
        return normalize_mcp_servers(payload.get("servers"))
    return normalize_mcp_servers(payload)


def save_mcp_servers(root: Path, servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = normalize_mcp_servers(servers)
    path = mcp_servers_store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"servers": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def set_mcp_server_status(
    server_id: str,
    *,
    state: str,
    message: str = "",
    tool_count: int | None = None,
) -> None:
    _SERVER_STATUS[server_id] = {
        "state": state,
        "message": message,
        "toolCount": tool_count,
    }


def get_mcp_server_status(server_id: str) -> dict[str, Any]:
    return deepcopy(
        _SERVER_STATUS.get(
            server_id,
            {
                "state": "unknown",
                "message": "",
                "toolCount": None,
            },
        )
    )


def load_mcp_servers_with_status(root: Path) -> list[dict[str, Any]]:
    return [
        {
            **server,
            "status": get_mcp_server_status(str(server.get("id") or "")),
        }
        for server in load_mcp_servers(root)
    ]
