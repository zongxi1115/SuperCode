from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Any, Callable


TRANSIENT_MCP_ERROR_PATTERNS = (
    "client network socket disconnected",
    "connection closed",
    "econnreset",
    "etimedout",
    "fetch failed",
    "network socket",
    "socket hang up",
    "tls connection",
)
MCP_RETRY_ATTEMPTS = 3
MCP_TOOL_CACHE_TTL_SECONDS = 300
_TOOLS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _require_mcp_sdk() -> tuple[type[Any], type[Any]]:
    try:
        from mcp import ClientSession, StdioServerParameters
    except ImportError as exc:
        raise RuntimeError("缺少 MCP Python SDK，请先安装 fastapi_app/requirements.txt 中的 mcp 依赖。") from exc
    return ClientSession, StdioServerParameters


def _load_stdio_client() -> Callable[..., Any]:
    try:
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("当前 MCP Python SDK 不支持 stdio client。") from exc
    return stdio_client


def _load_streamable_http_client() -> Callable[..., Any]:
    try:
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        try:
            from mcp.client.streamable_http import streamablehttp_client as streamable_http_client
        except ImportError as exc:
            raise RuntimeError("当前 MCP Python SDK 不支持 Streamable HTTP client。") from exc
    return streamable_http_client


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(by_alias=True, exclude_none=True))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _tool_schema(tool_payload: dict[str, Any]) -> dict[str, Any]:
    schema = (
        tool_payload.get("inputSchema")
        or tool_payload.get("input_schema")
        or tool_payload.get("parameters")
    )
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


def _normalize_tool(tool: Any) -> dict[str, Any]:
    payload = _jsonable(tool)
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    return {
        "name": name,
        "description": description,
        "parameters_schema": _tool_schema(payload),
    }


def _normalize_tool_result(result: Any) -> Any:
    payload = _jsonable(result)
    if not isinstance(payload, dict):
        return payload
    content = payload.get("content")
    structured = payload.get("structuredContent", payload.get("structured_content"))
    is_error = bool(payload.get("isError", payload.get("is_error", False)))
    if structured is not None:
        return {
            "structuredContent": structured,
            "content": content,
            "isError": is_error,
        }
    if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict):
        text = content[0].get("text")
        if isinstance(text, str):
            return text
    return payload


def _http_headers(server: dict[str, Any]) -> dict[str, str]:
    headers = {
        str(key): str(value)
        for key, value in (server.get("headers") or {}).items()
        if str(key).strip()
    }
    bearer_token = str(server.get("bearerToken") or "").strip()
    if bearer_token and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def _decode_stdio_stderr(raw_stderr: bytes) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return raw_stderr.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw_stderr.decode("utf-8", errors="replace").strip()


def _server_cache_key(server: dict[str, Any]) -> str:
    payload = {
        "transport": server.get("transport"),
        "command": server.get("command"),
        "args": server.get("args"),
        "env": server.get("env"),
        "url": server.get("url"),
        "bearerToken": bool(str(server.get("bearerToken") or "").strip()),
        "headers": server.get("headers"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _cached_tools(server: dict[str, Any]) -> list[dict[str, Any]] | None:
    cached = _TOOLS_CACHE.get(_server_cache_key(server))
    if cached is None:
        return None
    cached_at, tools = cached
    if time.monotonic() - cached_at > MCP_TOOL_CACHE_TTL_SECONDS:
        _TOOLS_CACHE.pop(_server_cache_key(server), None)
        return None
    return [dict(tool) for tool in tools]


def _remember_tools(server: dict[str, Any], tools: list[dict[str, Any]]) -> None:
    _TOOLS_CACHE[_server_cache_key(server)] = (
        time.monotonic(),
        [dict(tool) for tool in tools],
    )


def _is_transient_mcp_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(pattern in text for pattern in TRANSIENT_MCP_ERROR_PATTERNS)


async def _retry_transient_mcp_error(
    operation: Callable[[], Awaitable[Any]],
) -> Any:
    last_error: BaseException | None = None
    for attempt in range(MCP_RETRY_ATTEMPTS):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001 - retry only known transport/network failures
            last_error = exc
            if attempt >= MCP_RETRY_ATTEMPTS - 1 or not _is_transient_mcp_error(exc):
                raise
            await asyncio.sleep(0.6 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("MCP 调用失败。")


@asynccontextmanager
async def _client_session(server: dict[str, Any]):
    ClientSession, StdioServerParameters = _require_mcp_sdk()
    transport = str(server.get("transport") or "stdio")
    if transport == "streamable_http":
        url = str(server.get("url") or "").strip()
        if not url:
            raise ValueError("Streamable HTTP MCP server 缺少 URL。")
        streamable_http_client = _load_streamable_http_client()
        async with streamable_http_client(url, headers=_http_headers(server) or None) as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
        return

    command = str(server.get("command") or "").strip()
    if not command:
        raise ValueError("stdio MCP server 缺少启动命令。")
    args = [str(item) for item in server.get("args") or [] if str(item).strip()]
    env = {
        str(key): str(value)
        for key, value in (server.get("env") or {}).items()
        if str(key).strip()
    }
    stdio_client = _load_stdio_client()
    params = StdioServerParameters(command=command, args=args, env={**os.environ, **env} if env else None)
    with tempfile.TemporaryFile(mode="w+b") as errlog:
        try:
            async with stdio_client(params, errlog=errlog) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        except Exception as exc:
            errlog.seek(0)
            stderr_text = _decode_stdio_stderr(errlog.read())
            if stderr_text:
                raise RuntimeError(
                    f"{exc}\n\nMCP server stderr:\n{stderr_text[-4000:]}"
                ) from exc
            raise


async def _list_mcp_tools_once(server: dict[str, Any]) -> list[dict[str, Any]]:
    async with _client_session(server) as session:
        response = await session.list_tools()
    tools = getattr(response, "tools", [])
    normalized = [_normalize_tool(tool) for tool in tools]
    return [tool for tool in normalized if tool["name"]]


async def list_mcp_tools_async(server: dict[str, Any], *, use_cache: bool = True) -> list[dict[str, Any]]:
    if use_cache:
        cached = _cached_tools(server)
        if cached is not None:
            return cached
    try:
        tools = await _retry_transient_mcp_error(lambda: _list_mcp_tools_once(server))
    except Exception as exc:
        cached = _cached_tools(server)
        if cached is not None and _is_transient_mcp_error(exc):
            return cached
        raise
    _remember_tools(server, tools)
    return tools


async def _call_mcp_tool_once(server: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> Any:
    async with _client_session(server) as session:
        response = await session.call_tool(tool_name, arguments=arguments or {})
    return _normalize_tool_result(response)


async def call_mcp_tool_async(server: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> Any:
    return await _retry_transient_mcp_error(
        lambda: _call_mcp_tool_once(server, tool_name, arguments)
    )


def run_mcp_coro(coro_factory: Callable[[], Awaitable[Any]]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 - transfer exception across thread boundary
            result["error"] = exc

    import threading

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def list_mcp_tools(server: dict[str, Any], *, use_cache: bool = True) -> list[dict[str, Any]]:
    return run_mcp_coro(lambda: list_mcp_tools_async(server, use_cache=use_cache))


def call_mcp_tool(server: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> Any:
    return run_mcp_coro(lambda: call_mcp_tool_async(server, tool_name, arguments))
