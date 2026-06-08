from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from fastapi_app.api_models import CreateTerminalRequest, TerminalControlRequest, TerminalInputRequest
from fastapi_app.runtime.terminal import TerminalRuntime

TERMINAL_WS_INITIAL_REPLAY_MAX_CHARS = 64_000
TERMINAL_WS_OUTPUT_CHUNK_CHARS = 8_192


@dataclass(frozen=True)
class TerminalRouteDeps:
    require_session: Callable[[str], Any]
    is_desktop_mode: Callable[[], bool]


def register_terminal_routes(
    app: FastAPI,
    *,
    deps: TerminalRouteDeps,
) -> None:
    @app.get("/api/sessions/{session_id}/terminal")
    async def get_session_terminal(
        session_id: str,
        include_output: bool = Query(False),
        include_file_tree: bool = Query(False),
        include_processes: bool = Query(False),
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.terminal_runtime is None:
            raise HTTPException(status_code=404, detail="terminal 不存在")
        snapshot = session.terminal_snapshot(
            include_output=include_output,
            include_file_tree=include_file_tree,
            include_processes=include_processes,
        )
        return JSONResponse(snapshot.model_dump())

    @app.post("/api/sessions/{session_id}/terminal/input")
    async def post_session_terminal_input(
        session_id: str,
        request: TerminalInputRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.terminal_runtime is None:
            raise HTTPException(status_code=404, detail="terminal 不存在")
        key = str(request.key or "").strip()
        if key:
            try:
                handled = session.terminal_runtime.send_key(key)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not handled:
                raise HTTPException(status_code=409, detail="当前终端后端不支持该按键")
        elif request.command == "" and not request.submit:
            raise HTTPException(status_code=400, detail="command 和 submit 不能同时为空")
        else:
            session.terminal_runtime.send_input(request.command, submit=request.submit)
        session.touch()
        snapshot = session.terminal_runtime.snapshot(session_id)
        session.terminal_output = snapshot.output
        return JSONResponse(snapshot.model_dump())

    @app.post("/api/sessions/{session_id}/terminal/control")
    async def post_session_terminal_control(
        session_id: str,
        request: TerminalControlRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.terminal_runtime is None:
            raise HTTPException(status_code=404, detail="terminal 不存在")
        if request.action == "interrupt" and not session.terminal_runtime.interrupt():
            raise HTTPException(status_code=409, detail="当前终端后端不支持 Ctrl+C 中断")
        session.touch()
        snapshot = session.terminal_runtime.snapshot(session_id)
        session.terminal_output = snapshot.output
        return JSONResponse(snapshot.model_dump())

    @app.post("/api/sessions/{session_id}/terminal/clear")
    async def post_session_terminal_clear(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        if session.terminal_runtime is None:
            raise HTTPException(status_code=404, detail="terminal 不存在")
        session.terminal_runtime.clear()
        snapshot = session.terminal_runtime.snapshot(session_id)
        session.terminal_output = snapshot.output
        return JSONResponse(snapshot.model_dump())

    @app.get("/api/sessions/{session_id}/terminals")
    async def list_session_terminals(session_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        terminals: list[dict[str, Any]] = []
        for tid, runtime in session.terminal_runtimes.items():
            snapshot = runtime.snapshot(session_id, include_output=False)
            terminals.append({
                "terminalId": tid,
                "name": "PowerShell" if tid == "main" else tid,
                "shell": snapshot.shell,
                "backend": snapshot.backend,
                "cwd": snapshot.cwd or session.workspace,
                "isAlive": snapshot.isAlive,
                "isDefault": tid == session.default_terminal_id,
                "kind": "interactive",
            })
        if session.interactive_command_session is not None:
            for proc in session.interactive_command_session.list_managed_processes(only_active=True):
                terminals.append({
                    "terminalId": proc["terminalId"],
                    "name": proc["terminalId"],
                    "shell": "powershell",
                    "backend": "managed",
                    "cwd": session.workspace,
                    "isAlive": proc["status"] in ("running", "orphaned"),
                    "isDefault": False,
                    "kind": "managed-process",
                    "command": proc["command"],
                    "rootPid": proc["rootPid"],
                    "status": proc["status"],
                    "startedAt": proc["startedAt"],
                })
        return JSONResponse({"terminals": terminals})

    @app.post("/api/sessions/{session_id}/terminals")
    async def create_session_terminal(
        session_id: str,
        request: CreateTerminalRequest,
    ) -> JSONResponse:
        session = deps.require_session(session_id)
        if deps.is_desktop_mode():
            raise HTTPException(status_code=400, detail="桌面模式暂不启用交互终端")
        if len(session.terminal_runtimes) >= 8:
            raise HTTPException(status_code=400, detail="终端数量已达上限（8 个）")
        terminal_id = f"term_{uuid.uuid4().hex[:6]}"
        workspace = session.workspace
        default_runtime = session.get_terminal(session.default_terminal_id)
        inherited_cwd = None
        if default_runtime is not None:
            try:
                inherited_cwd = default_runtime.snapshot(session_id, include_output=False).cwd
            except Exception:
                inherited_cwd = None
        cwd = request.cwd or inherited_cwd or workspace
        name = request.name or f"PowerShell {len(session.terminal_runtimes) + 1}"
        runtime = TerminalRuntime(workspace=workspace)
        if cwd != workspace:
            runtime.send_input(f"Set-Location -LiteralPath '{cwd}'", submit=True)
        session.terminal_runtimes[terminal_id] = runtime
        session.touch()
        snapshot = runtime.snapshot(session_id, include_output=False)
        return JSONResponse({
            "terminalId": terminal_id,
            "name": name,
            "shell": snapshot.shell,
            "backend": snapshot.backend,
            "cwd": snapshot.cwd or workspace,
            "isAlive": snapshot.isAlive,
            "isDefault": terminal_id == session.default_terminal_id,
            "kind": "interactive",
        })

    @app.delete("/api/sessions/{session_id}/terminals/{terminal_id}")
    async def close_session_terminal(session_id: str, terminal_id: str) -> JSONResponse:
        session = deps.require_session(session_id)
        if terminal_id == session.default_terminal_id:
            raise HTTPException(status_code=400, detail="不能关闭默认终端")
        runtime = session.terminal_runtimes.pop(terminal_id, None)
        if runtime is None:
            raise HTTPException(status_code=404, detail="终端不存在")
        runtime.close()
        session.touch()
        return JSONResponse({"closed": True, "terminalId": terminal_id})

    @app.websocket("/api/sessions/{session_id}/terminal/ws")
    async def session_terminal_websocket(
        websocket: WebSocket,
        session_id: str,
        terminal_id: str | None = Query(None),
    ) -> None:
        session = deps.require_session(session_id)
        resolved_id = terminal_id or session.default_terminal_id
        runtime = session.get_terminal(resolved_id) if resolved_id else None
        if runtime is None:
            await websocket.close(code=1011, reason="terminal 不存在")
            return

        await websocket.accept()
        loop = asyncio.get_running_loop()
        output_queue: asyncio.Queue[str | None] = asyncio.Queue()
        send_lock = asyncio.Lock()

        def enqueue_output(chunk: str) -> None:
            loop.call_soon_threadsafe(output_queue.put_nowait, chunk)

        unsubscribe = runtime.read_loop(enqueue_output)

        async def send_terminal_message(message: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(message)

        async def send_terminal_status() -> None:
            snapshot = runtime.snapshot(
                session_id,
                include_output=False,
            )
            await send_terminal_message(
                {
                    "type": "status",
                    "cwd": snapshot.cwd,
                    "backend": snapshot.backend,
                    "supportsInterrupt": snapshot.supportsInterrupt,
                    "supportsResize": snapshot.supportsResize,
                }
            )

        async def send_runtime_output() -> None:
            snapshot = runtime.snapshot(
                session_id,
                include_output=True,
                output_tail_chars=TERMINAL_WS_INITIAL_REPLAY_MAX_CHARS,
            )
            await send_terminal_status()
            if snapshot.output:
                for start in range(0, len(snapshot.output), TERMINAL_WS_OUTPUT_CHUNK_CHARS):
                    await send_terminal_message(
                        {
                            "type": "output",
                            "data": snapshot.output[
                                start : start + TERMINAL_WS_OUTPUT_CHUNK_CHARS
                            ],
                        }
                    )
            session.terminal_output = runtime.snapshot(
                session_id,
                include_output=True,
            ).output

            while True:
                chunk = await output_queue.get()
                if chunk is None:
                    break
                chunks = [chunk]
                buffered_chars = len(chunk)
                deadline = time.monotonic() + 0.016
                while time.monotonic() < deadline and buffered_chars < 64_000:
                    try:
                        next_chunk = output_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if next_chunk is None:
                        await output_queue.put(None)
                        break
                    chunks.append(next_chunk)
                    buffered_chars += len(next_chunk)
                await send_terminal_message({"type": "output", "data": "".join(chunks)})

        async def receive_terminal_input() -> None:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    await send_terminal_message({"type": "error", "message": "无效的终端消息"})
                    continue

                message_type = str(message.get("type") or "").strip().lower()
                if message_type == "input":
                    runtime.write(str(message.get("data") or ""))
                    continue
                if message_type == "resize":
                    try:
                        cols = int(message.get("cols") or 0)
                        rows = int(message.get("rows") or 0)
                    except (TypeError, ValueError):
                        continue
                    runtime.resize(cols, rows)
                    continue
                if message_type == "clear":
                    runtime.clear()
                    session.terminal_output = ""
                    await send_terminal_message({"type": "clear"})
                    await send_terminal_status()
                    continue
                if message_type == "interrupt":
                    if not runtime.interrupt():
                        await send_terminal_message(
                            {"type": "error", "message": "当前终端后端不支持 Ctrl+C 中断"}
                        )
                    await send_terminal_status()
                    continue
                await send_terminal_message(
                    {"type": "error", "message": f"不支持的终端消息类型: {message_type}"}
                )

        sender = asyncio.create_task(send_runtime_output())
        receiver = asyncio.create_task(receive_terminal_input())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass
        except Exception:
            with suppress(Exception):
                await send_terminal_message(
                    {"type": "error", "message": "终端连接已断开"}
                )
        finally:
            unsubscribe()
            await output_queue.put(None)
            sender.cancel()
            receiver.cancel()

