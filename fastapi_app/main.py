from __future__ import annotations

import asyncio
import json
import subprocess
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent import AgentEvent, AgentLLMConfig, ChatSession, CodingAgent, OpenAICompatibleClient
from coding_agent import CodingPromptBrain, build_coding_tools

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT
DEFAULT_SELECTED_FILE = None
DEFAULT_OPEN_FILES = [
    "ChatLayout.tsx",
    "MessageList.tsx",
    "TerminalPanel.tsx",
    "ToolPanel.tsx",
    "FilePreview.tsx",
]


class CreateSessionResponse(BaseModel):
    sessionId: str
    model: str
    mode: str
    startupError: str | None
    workspace: str
    workspaceOptions: list[dict[str, str]]
    messages: list[dict[str, Any]]
    toolCalls: list[dict[str, Any]]
    thoughts: list[str]
    terminalOutput: str
    fileTree: list[dict[str, Any]]
    selectedFilePath: str | None
    selectedFileContent: str
    openFiles: list[str]
    planSteps: list[dict[str, str]]


class SessionContextMessage(BaseModel):
    role: str
    content: str


class SessionContextTool(BaseModel):
    id: str
    name: str
    state: str
    success: bool | None = None


class SessionContextResponse(BaseModel):
    sessionId: str
    workspace: str
    mode: str
    model: str
    selectedFilePath: str | None
    openFiles: list[str]
    messageCount: int
    toolCallCount: int
    thoughtCount: int
    estimatedTokens: int
    maxTokens: int
    recentMessages: list[SessionContextMessage]
    recentThoughts: list[str]
    recentTools: list[SessionContextTool]
    planSteps: list[dict[str, str]]


class CreateSessionRequest(BaseModel):
    workspace: str | None = None


class SessionHistoryItem(BaseModel):
    sessionId: str
    workspace: str
    mode: str
    model: str
    title: str
    preview: str
    messageCount: int
    toolCallCount: int
    createdAt: int
    updatedAt: int


class ChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    message: str


class TerminalInputRequest(BaseModel):
    command: str


class TerminalSnapshotResponse(BaseModel):
    sessionId: str
    output: str
    revision: int
    isAlive: bool
    shell: str


@dataclass
class TerminalRuntime:
    workspace: str
    shell: str = "powershell"
    output: str = ""
    revision: int = 0
    process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    stdout_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    stderr_thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.process = subprocess.Popen(
            [
                "powershell",
                "-NoLogo",
                "-NoProfile",
                "-NoExit",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                    "chcp 65001 > $null"
                ),
            ],
            cwd=self.workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_stream,
            args=(self.process.stdout,),
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._pump_stream,
            args=(self.process.stderr,),
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _pump_stream(self, stream: Any) -> None:
        try:
            while True:
                chunk = stream.readline()
                if chunk == "":
                    break
                self.append_output(chunk)
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def append_output(self, text: str) -> None:
        with self.lock:
            self.output += text
            self.revision += 1

    def write(self, command: str) -> None:
        clean = command.rstrip("\r\n")
        if not clean:
            return
        prompt = f"PS {self.workspace}> {clean}\n"
        self.append_output(prompt)
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("terminal process is not available")
        self.process.stdin.write(clean + "\n")
        self.process.stdin.flush()

    def snapshot(self, session_id: str) -> TerminalSnapshotResponse:
        with self.lock:
            return TerminalSnapshotResponse(
                sessionId=session_id,
                output=self.output,
                revision=self.revision,
                isAlive=self.is_alive(),
                shell=self.shell,
            )

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def clear(self) -> None:
        with self.lock:
            self.output = ""
            self.revision += 1

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin is not None:
                self.process.stdin.write("exit\n")
                self.process.stdin.flush()
        except Exception:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


@dataclass
class UISession:
    session_id: str
    model: str
    workspace: str
    mode: str = "demo"
    startup_error: str | None = None
    selected_file_path: str | None = DEFAULT_SELECTED_FILE
    open_files: list[str] = field(default_factory=lambda: list(DEFAULT_OPEN_FILES))
    terminal_output: str = ""
    terminal_runtime: TerminalRuntime | None = field(default=None, repr=False)
    chat_session: ChatSession | None = None
    history_messages: list[dict[str, Any]] = field(default_factory=list)
    history_tools: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    plan_steps: list[dict[str, str]] = field(
        default_factory=lambda: [
            {
                "id": "1",
                "title": "分析需求，确认界面结构与布局",
                "description": "聊天区、代码区、文件树、终端与工具链同时在线。",
                "status": "completed",
            },
            {
                "id": "2",
                "title": "设计组件层级和数据流",
                "description": "消息流、工具流、文件流和终端流分层管理。",
                "status": "in_progress",
            },
            {
                "id": "3",
                "title": "实现聊天面板与消息流式输出",
                "description": "普通文本尽量实时推送，工具链单独展示。",
                "status": "pending",
            },
            {
                "id": "4",
                "title": "集成文件预览与终端执行能力",
                "description": "文件树联动代码预览，命令输出持续滚动。",
                "status": "pending",
            },
            {
                "id": "5",
                "title": "完善工具面板与状态管理",
                "description": "沉淀调用历史、错误状态和执行结果。",
                "status": "pending",
            },
        ]
    )

    def snapshot(self) -> CreateSessionResponse:
        if self.terminal_runtime is not None:
            self.terminal_output = self.terminal_runtime.snapshot(self.session_id).output
        return CreateSessionResponse(
            sessionId=self.session_id,
            model=self.model,
            mode=self.mode,
            startupError=self.startup_error,
            workspace=self.workspace,
            workspaceOptions=list_workspace_options(),
            messages=self.history_messages,
            toolCalls=self.history_tools,
            thoughts=self.thoughts,
            terminalOutput=self.terminal_output,
            fileTree=build_file_tree(resolve_workspace_path(self.workspace)),
            selectedFilePath=self.selected_file_path,
            selectedFileContent=read_text_file(self.selected_file_path, self.workspace),
            openFiles=self.open_files,
            planSteps=self.plan_steps,
        )

    def history_snapshot(self) -> SessionHistoryItem:
        return SessionHistoryItem(
            sessionId=self.session_id,
            workspace=self.workspace,
            mode=self.mode,
            model=self.model,
            title=self.summary_title(),
            preview=self.summary_preview(),
            messageCount=len(self.history_messages),
            toolCallCount=len(self.history_tools),
            createdAt=self.created_at,
            updatedAt=self.updated_at,
        )

    def context_snapshot(self) -> SessionContextResponse:
        recent_messages = [
            SessionContextMessage(
                role=str(message.get("role", "")),
                content=str(message.get("content", "")),
            )
            for message in self.history_messages[-6:]
        ]
        recent_tools = [
            SessionContextTool(
                id=str(tool.get("id", "")),
                name=str(tool.get("name", "")),
                state=str(tool.get("state", "running")),
                success=tool.get("success") if isinstance(tool.get("success"), bool) else None,
            )
            for tool in self.history_tools[-8:]
        ]
        return SessionContextResponse(
            sessionId=self.session_id,
            workspace=self.workspace,
            mode=self.mode,
            model=self.model,
            selectedFilePath=self.selected_file_path,
            openFiles=self.open_files[-6:],
            messageCount=len(self.history_messages),
            toolCallCount=len(self.history_tools),
            thoughtCount=len(self.thoughts),
            estimatedTokens=estimate_session_tokens(self),
            maxTokens=infer_model_context_limit(self.model),
            recentMessages=recent_messages,
            recentThoughts=self.thoughts[-6:],
            recentTools=recent_tools,
            planSteps=self.plan_steps,
        )

    def touch(self) -> None:
        self.updated_at = int(time.time() * 1000)

    def summary_title(self) -> str:
        for message in self.history_messages:
            if str(message.get("role")) == "user":
                content = compact_text(str(message.get("content", "")), 40)
                if content:
                    return content
        workspace_name = Path(self.workspace).name or self.workspace
        return f"{workspace_name} 新对话"

    def summary_preview(self) -> str:
        for message in reversed(self.history_messages):
            content = compact_text(str(message.get("content", "")), 72)
            if content:
                return content
        return "还没有消息内容"


app = FastAPI(title="SuperCode Agent UI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, UISession] = {}


@app.on_event("shutdown")
def shutdown_terminals() -> None:
    for session in _sessions.values():
        if session.terminal_runtime is not None:
            session.terminal_runtime.close()


@app.get("/api/workspaces")
async def get_workspaces() -> JSONResponse:
    return JSONResponse({"workspaces": list_workspace_options()})


@app.get("/api/directories")
async def get_directories(path: str = Query(...)) -> JSONResponse:
    root = normalize_workspace(path)
    return JSONResponse({"path": str(root), "children": list_child_directories(root)})


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest) -> JSONResponse:
    session_id = uuid.uuid4().hex
    workspace = normalize_workspace(request.workspace)
    chat_session, model_name, startup_error = build_chat_session(workspace)
    session = UISession(
        session_id=session_id,
        model=model_name,
        workspace=workspace,
        terminal_runtime=TerminalRuntime(workspace=workspace),
        chat_session=chat_session,
        mode="agent" if chat_session is not None else "demo",
        startup_error=startup_error,
        selected_file_path=pick_default_file(workspace),
        open_files=build_default_open_files(workspace),
    )
    _sessions[session_id] = session
    return JSONResponse(session.snapshot().model_dump())


@app.get("/api/sessions/history")
async def get_session_history() -> JSONResponse:
    history = sorted(
        (session.history_snapshot().model_dump() for session in _sessions.values()),
        key=lambda item: item["updatedAt"],
        reverse=True,
    )
    return JSONResponse({"sessions": history})


@app.get("/api/sessions/{session_id}")
async def get_session_snapshot(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(session.snapshot().model_dump())


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    session = _sessions.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    if session.terminal_runtime is not None:
        session.terminal_runtime.close()
    return JSONResponse({"deleted": True, "sessionId": session_id})


@app.get("/api/files")
async def get_file(
    session_id: str = Query(...),
    path: str = Query(...),
) -> JSONResponse:
    session = require_session(session_id)
    session.selected_file_path = normalize_relative_path(path, session.workspace)

    filename = Path(session.selected_file_path).name
    if filename not in session.open_files:
        session.open_files.append(filename)
    session.touch()

    return JSONResponse(
        {
            "selectedFilePath": session.selected_file_path,
            "selectedFileContent": read_text_file(session.selected_file_path, session.workspace),
            "openFiles": session.open_files[-6:],
        }
    )


@app.get("/api/sessions/{session_id}/file-tree")
async def get_file_tree(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(
        {
            "fileTree": build_file_tree(resolve_workspace_path(session.workspace)),
        },
    )


@app.put("/api/files")
async def save_file(
    session_id: str = Query(...),
    path: str = Query(...),
    body: dict | None = Body(None),
) -> JSONResponse:
    session = require_session(session_id)
    resolved_path = normalize_relative_path(path, session.workspace)
    target = Path(resolved_path).expanduser().resolve()
    workspace_root = resolve_workspace_path(session.workspace)
    if workspace_root != target and workspace_root not in target.parents:
        return JSONResponse({"error": "路径不在工作区内"}, status_code=403)
    content = body.get("content", "") if body else ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        session.touch()
        return JSONResponse({"saved": True, "path": resolved_path})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/sessions/{session_id}/context")
async def get_session_context(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(session.context_snapshot().model_dump())


@app.get("/api/sessions/{session_id}/terminal")
async def get_session_terminal(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    snapshot = session.terminal_runtime.snapshot(session_id)
    session.terminal_output = snapshot.output
    return JSONResponse(snapshot.model_dump())


@app.post("/api/sessions/{session_id}/terminal/input")
async def post_session_terminal_input(
    session_id: str,
    request: TerminalInputRequest,
) -> JSONResponse:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    command = request.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="command 不能为空")
    session.terminal_runtime.write(command)
    session.touch()
    snapshot = session.terminal_runtime.snapshot(session_id)
    session.terminal_output = snapshot.output
    return JSONResponse(snapshot.model_dump())


@app.post("/api/sessions/{session_id}/terminal/clear")
async def post_session_terminal_clear(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    session.terminal_runtime.clear()
    snapshot = session.terminal_runtime.snapshot(session_id)
    session.terminal_output = snapshot.output
    return JSONResponse(snapshot.model_dump())


@app.post("/api/chat/stream")
async def chat_stream(request: ChatStreamRequest) -> StreamingResponse:
    session = require_session(request.session_id)
    user_message = request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        user_message_id = uuid.uuid4().hex
        await queue.put(
            {
                "type": "user_message",
                "payload": {
                    "id": user_message_id,
                    "content": user_message,
                },
            }
        )
        session.history_messages.append(
            {"id": user_message_id, "role": "user", "content": user_message}
        )
        session.touch()

        producer = asyncio.create_task(
            run_demo_stream(session, user_message, queue)
            if session.chat_session is None
            else run_agent_stream(session, user_message, queue)
        )

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            await producer

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def require_session(session_id: str) -> UISession:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    return session


def build_chat_session(workspace: str) -> tuple[ChatSession | None, str, str | None]:
    try:
        config = AgentLLMConfig.from_env(ROOT / ".env")
        client = OpenAICompatibleClient(config)
        agent = CodingAgent(
            brain=CodingPromptBrain(client),
            tools=build_coding_tools(),
            workspace=resolve_workspace_path(workspace),
            max_steps=config.max_steps,
        )
        return ChatSession(agent=agent), config.model, None
    except Exception as exc:  # noqa: BLE001 - 需要把启动失败原因回传给前端
        return None, "Claude 3.5 Sonnet · Demo", str(exc)


async def run_agent_stream(
    session: UISession,
    user_message: str,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    loop = asyncio.get_running_loop()
    assistant_id = uuid.uuid4().hex
    streamed_assistant_text = ""
    assistant_stream_started = False

    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )

    def on_event(event: AgentEvent) -> None:
        nonlocal streamed_assistant_text, assistant_stream_started

        if event.type == "thought_delta" and event.delta:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "thought_delta",
                    "payload": {
                        "assistant_id": assistant_id,
                        "delta": event.delta,
                        "thought": event.thought or "",
                    },
                },
            )
            return

        if event.type == "thought":
            thought_text = event.thought or ""
            if thought_text:
                session.thoughts.append(thought_text)
                session.touch()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "thought",
                    "payload": {
                        "assistant_id": assistant_id,
                        "thought": thought_text,
                    },
                },
            )
            return

        if event.type == "final_answer_delta" and event.delta:
            if not assistant_stream_started:
                assistant_stream_started = True
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "assistant_reset", "payload": {"id": assistant_id}},
                )

            streamed_assistant_text += event.delta
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "assistant_delta",
                    "payload": {
                        "id": assistant_id,
                        "delta": event.delta,
                    },
                },
            )
            return

        if event.type == "tool_call" and event.tool_call is not None:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            update_plan_steps_for_tool(session, event.step_index, event.tool_call.name)
            if event.tool_call.name == "read_file":
                maybe_filename = event.tool_call.arguments.get("filename")
                if isinstance(maybe_filename, str):
                    session.selected_file_path = normalize_relative_path(maybe_filename, session.workspace)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_call",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                        "thought": event.thought or "",
                    },
                },
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "plan_steps",
                    "payload": {
                        "steps": session.plan_steps,
                    },
                },
            )
            return

        if event.type == "tool_result" and event.tool_call is not None and event.tool_result is not None:
            tool_id = event.tool_call.id or event.tool_result.tool_call_id or f"step-{event.step_index}-{event.tool_call.name}"
            output = event.tool_result.output
            if event.tool_result.name in {"execute", "excecute"} and isinstance(output, str):
                session.terminal_output = output
            tool_record = {
                "id": tool_id,
                "stepIndex": event.step_index,
                "name": event.tool_call.name,
                "arguments": event.tool_call.arguments,
                "output": output,
                "success": event.tool_result.success,
                "errorMessage": event.tool_result.error_message,
                "state": "completed" if event.tool_result.success else "error",
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            session.touch()
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_result",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                        "output": output,
                        "success": event.tool_result.success,
                        "error_message": event.tool_result.error_message,
                    },
                },
            )
            return

        if event.type in {"final", "turn_finished", "limit_reached"}:
            finalize_plan_steps(session)
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "plan_steps",
                    "payload": {
                        "steps": session.plan_steps,
                    },
                },
            )

    try:
        response = await asyncio.to_thread(
            session.chat_session.ask,
            user_message,
            on_event,
        )
    except Exception as exc:  # noqa: BLE001 - 流式接口需要兜底，避免 SSE 半路中断
        finalize_plan_steps(session)
        await queue.put(
            {
                "type": "plan_steps",
                "payload": {
                    "steps": session.plan_steps,
                },
            }
        )

        failure_message = (
            f"\n\n后端处理在流式阶段失败：{exc}"
            if assistant_stream_started
            else f"后端处理失败：{exc}"
        )
        if not assistant_stream_started:
            await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})

        for chunk in chunk_text(failure_message):
            if not chunk:
                continue
            await queue.put(
                {
                    "type": "assistant_delta",
                    "payload": {
                        "id": assistant_id,
                        "delta": chunk,
                    },
                }
            )

        session.history_messages.append(
            {
                "id": assistant_id,
                "role": "assistant",
                "content": failure_message.strip(),
            }
        )
        session.touch()
        await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
        await queue.put(None)
        return

    session.history_messages.append(
        {
            "id": assistant_id,
            "role": "assistant",
            "content": response.final_output,
        }
    )
    session.touch()
    remaining_output = response.final_output
    should_reset_before_replay = not assistant_stream_started
    if assistant_stream_started:
        if response.final_output.startswith(streamed_assistant_text):
            remaining_output = response.final_output[len(streamed_assistant_text) :]
        else:
            should_reset_before_replay = True
            remaining_output = response.final_output

    if should_reset_before_replay:
        await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})

    for chunk in chunk_text(remaining_output):
        if not chunk:
            continue
        await queue.put(
            {
                "type": "assistant_delta",
                "payload": {
                    "id": assistant_id,
                    "delta": chunk,
                },
            }
        )
        await asyncio.sleep(0.03)

    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)


async def run_demo_stream(
    session: UISession,
    user_message: str,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    assistant_id = uuid.uuid4().hex
    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )
    demo_file = pick_demo_file(session.workspace)
    demo_events = [
        ("thought", {"thought": f"先分析当前工作区 {session.workspace}，确认目录结构和可操作文件。"}),
        (
            "tool_call",
            {
                "id": "step-1-list_file",
                "step_index": 1,
                "name": "list_file",
                "arguments": {"path": "."},
                "thought": "先看当前工作区顶层结构，确认接下来要读哪些文件。",
            },
        ),
        (
            "tool_result",
            {
                "id": "step-1-list_file",
                "step_index": 1,
                "name": "list_file",
                "arguments": {"path": "."},
                "output": render_demo_list_output(session.workspace),
                "success": True,
                "error_message": None,
            },
        ),
        ("thought", {"thought": "接着挑一个代表性文件读一下，验证文件预览和工具链是否同步。"}),
        (
            "tool_call",
            {
                "id": "step-2-read_file",
                "step_index": 2,
                "name": "read_file",
                "arguments": {"filename": demo_file or "", "start_line": 1, "end_line": 120},
                "thought": "读取示例文件，确认当前工作区里的代码内容能回显到右侧预览区。",
            },
        ),
        (
            "tool_result",
            {
                "id": "step-2-read_file",
                "step_index": 2,
                "name": "read_file",
                "arguments": {"filename": demo_file or "", "start_line": 1, "end_line": 120},
                "output": read_text_file(demo_file, session.workspace)[:1400] if demo_file else "当前工作区里暂时没有合适的文本文件可预览。",
                "success": bool(demo_file),
                "error_message": None if demo_file else "未找到可预览文件",
            },
        ),
    ]

    for event_type, payload in demo_events:
        if event_type == "thought":
            session.thoughts.append(str(payload["thought"]))
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        else:
            update_plan_steps_for_tool(
                session,
                payload.get("step_index"),
                str(payload.get("name", "")),
            )
            session.history_tools = upsert_tool(
                session.history_tools,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "output": payload.get("output"),
                    "success": payload.get("success"),
                    "errorMessage": payload.get("error_message"),
                    "state": "completed" if payload.get("success", True) else "error",
                    "thought": payload.get("thought"),
                },
            )
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        await queue.put({"type": event_type, "payload": payload})
        if event_type == "tool_call":
            await queue.put({"type": "plan_steps", "payload": {"steps": session.plan_steps}})
        await asyncio.sleep(0.18)

    answer = (
        f"已收到你的请求：{user_message}\n\n"
        "当前雏形会优先把聊天消息、思考步骤、工具调用链、文件树和终端输出全部打通。"
        "如果检测到真实模型配置，就会切到现有 Agent 执行循环；没有配置时则保持 demo 流，方便你先联调前端。"
    )
    session.history_messages.append({"id": assistant_id, "role": "assistant", "content": answer})
    session.touch()
    await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})
    for chunk in chunk_text(answer):
        await queue.put({"type": "assistant_delta", "payload": {"id": assistant_id, "delta": chunk}})
        await asyncio.sleep(0.03)

    finalize_plan_steps(session)
    await queue.put({"type": "plan_steps", "payload": {"steps": session.plan_steps}})
    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)


def upsert_tool(current: list[dict[str, Any]], next_tool: dict[str, Any]) -> list[dict[str, Any]]:
    for index, tool in enumerate(current):
        if tool["id"] == next_tool["id"]:
            updated = current[:]
            updated[index] = {**tool, **next_tool}
            return updated
    return [*current, next_tool]


def update_plan_steps_for_tool(session: UISession, step_index: int | None, tool_name: str) -> None:
    if not session.plan_steps:
        return

    if step_index is not None:
        for index, step in enumerate(session.plan_steps):
            numeric_id = index + 1
            if numeric_id < step_index:
                step["status"] = "completed"
            elif numeric_id == step_index:
                step["status"] = "in_progress"
            elif step["status"] != "completed":
                step["status"] = "pending"

    if tool_name in {"read_file", "list_file", "grep_file"}:
        session.plan_steps[1]["description"] = "已进入代码探索，正在读取结构、文件和引用关系。"
    elif tool_name in {"write_file", "replace_file"}:
        session.plan_steps[2]["description"] = "已开始落地修改，准备把变更写回工作区。"
    elif tool_name in {"execute", "excecute"}:
        session.plan_steps[3]["description"] = "正在执行命令并收集终端输出。"


def finalize_plan_steps(session: UISession) -> None:
    for step in session.plan_steps:
        step["status"] = "completed"
    if session.plan_steps:
        session.plan_steps[-1]["description"] = "本轮执行结束，工具结果和最终答复都已沉淀。"


def normalize_workspace(raw_workspace: str | None) -> str:
    if raw_workspace is None or not raw_workspace.strip():
        return str(DEFAULT_WORKSPACE.resolve())
    candidate = Path(raw_workspace.strip()).expanduser().resolve()
    if not candidate.exists():
        raise HTTPException(status_code=400, detail="工作区不存在")
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="工作区必须是目录")
    return str(candidate)


def resolve_workspace_path(workspace: str) -> Path:
    return Path(workspace).expanduser().resolve()


def normalize_relative_path(raw_path: str, workspace: str) -> str:
    workspace_path = resolve_workspace_path(workspace)
    candidate_path = Path(raw_path)
    workspace_candidate = (
        candidate_path.expanduser().resolve()
        if candidate_path.is_absolute()
        else (workspace_path / candidate_path).resolve()
    )
    if workspace_path != workspace_candidate and workspace_path not in workspace_candidate.parents:
        raise HTTPException(status_code=400, detail="路径越界")
    return str(workspace_candidate)


def build_file_tree(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    def walk(target: Path, prefix: Path) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            absolute = str(child.resolve())
            if child.is_dir():
                items.append(
                    {
                        "path": absolute,
                        "name": child.name,
                        "type": "folder",
                        "children": walk(child, prefix),
                    }
                )
            elif child.suffix in {".ts", ".tsx", ".css", ".json", ".py", ".md", ".toml", ".yaml", ".yml", ".js", ".jsx", ".mjs", ".cjs", ".html", ".sql", ".rs", ".go", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1", ".env", ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig", ".prettierrc", ".eslintrc", ".babelrc", ".svelte", ".vue", ".prisma", ".graphql", ".gql", ".proto", ".xml", ".ini", ".cfg", ".conf", ".config", ".lock", ".sum", ".mod", ".txt", ".log", ".diff", ".patch", ".svg", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".eot"}:
                items.append(
                    {
                        "path": absolute,
                        "name": child.name,
                        "type": "file",
                    }
                )
        return items

    return [
        {
            "path": str(root.resolve()),
            "name": root.name,
            "type": "folder",
            "children": walk(root, root),
        }
    ]


def read_text_file(relative_path: str | None, workspace: str) -> str:
    if relative_path is None or not str(relative_path).strip():
        return ""
    target = Path(relative_path).expanduser().resolve()
    workspace_root = resolve_workspace_path(workspace)
    if workspace_root != target and workspace_root not in target.parents:
        return ""
    if not target.exists() or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8")


def list_workspace_options() -> list[dict[str, str]]:
    seen: set[str] = set()
    options: list[dict[str, str]] = []

    def add(path: Path, label: str) -> None:
        resolved = str(path.expanduser().resolve())
        if resolved in seen or not Path(resolved).exists() or not Path(resolved).is_dir():
            return
        seen.add(resolved)
        options.append({"value": resolved, "label": label})

    add(DEFAULT_WORKSPACE.resolve(), "当前项目")
    add(DEFAULT_WORKSPACE.resolve().parent, "当前项目的上级目录")
    home = Path.home()
    add(home, "用户目录")
    add(home / "Desktop", "桌面")
    add(home / "Documents", "文档")

    for drive in ("C:/", "D:/", "E:/", "F:/"):
        add(Path(drive), drive.rstrip("/"))

    return options


def list_child_directories(path: str | Path) -> list[dict[str, str]]:
    root = Path(path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return []

    children: list[dict[str, str]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        children.append(
            {
                "value": str(child.resolve()),
                "label": child.name,
            }
        )
    return children


def build_default_open_files(workspace: str) -> list[str]:
    default_file = pick_default_file(workspace)
    if default_file is None:
        return []
    return [Path(default_file).name]


def pick_default_file(workspace: str) -> str | None:
    workspace_root = resolve_workspace_path(workspace)
    preferred_names = ["main.py", "App.tsx", "README.md", "index.tsx", "index.ts", "__init__.py"]
    for name in preferred_names:
        matches = list(workspace_root.rglob(name))
        if matches:
            return str(matches[0].resolve())

    for file_path in workspace_root.rglob("*"):
        if file_path.is_file() and file_path.suffix in {".py", ".ts", ".tsx", ".md", ".json"}:
            return str(file_path.resolve())
    return None


def pick_demo_file(workspace: str) -> str | None:
    return pick_default_file(workspace)


def render_demo_list_output(workspace: str) -> str:
    workspace_root = resolve_workspace_path(workspace)
    rendered = [f"# Path: {workspace_root}"]
    for child in sorted(workspace_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        rendered.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(rendered[:25])


def chunk_text(text: str, chunk_size: int = 28) -> list[str]:
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)] or [""]


def estimate_session_tokens(session: UISession) -> int:
    total_chars = 0
    for message in session.history_messages:
        total_chars += len(str(message.get("content", "")))
    for thought in session.thoughts:
        total_chars += len(thought)
    for tool in session.history_tools:
        total_chars += len(str(tool.get("name", "")))
        total_chars += len(json.dumps(tool.get("arguments", {}), ensure_ascii=False))
        output = tool.get("output")
        if output is not None:
            total_chars += len(str(output))
    total_chars += len(session.workspace)
    return max(1, total_chars // 4)


def infer_model_context_limit(model_name: str) -> int:
    normalized = model_name.lower()
    if "claude" in normalized:
        return 200_000
    if "gpt-4.1" in normalized or "gpt-5" in normalized or "qwen" in normalized:
        return 128_000
    if "gpt-4o-mini" in normalized or "gpt-4o" in normalized:
        return 128_000
    if "deepseek" in normalized:
        return 64_000
    return 32_000


def compact_text(value: str, limit: int) -> str:
    compact = " ".join(value.split()).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."
