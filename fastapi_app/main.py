from __future__ import annotations

from contextlib import asynccontextmanager, suppress

import signal

import asyncio
import json
import subprocess
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import re

try:
    from winpty import PtyProcess
except ImportError:  # pragma: no cover - optional dependency
    PtyProcess = None

from agent import AgentEvent, ChatSession, CodingAgent, ConversationMessage, OpenAICompatibleClient
from coding_agent import CodingPromptBrain, InteractiveCommandSession, build_coding_tools
from coding_agent.tools import delete_file_in_workspace, execute_git_commit, execute_git_tag, init_git_repo
from fastapi_app.model_config_store import (
    build_agent_config,
    config_store_path,
    discover_provider_models,
    list_model_options,
    load_ui_model_providers,
    resolve_model_option as resolve_stored_model_option,
    save_ui_model_providers,
    scan_env_model_sources,
)
from fastapi_app.session_store import PersistedSessionState, SQLiteSessionStateAdapter
from fastapi_app.ui_message_stream import UIMessageStreamAdapter, sse_data

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT
BACKEND_BASE_URL = "http://localhost:8000"
DEFAULT_BROWSER_PREVIEW_URL = "http://localhost:5173"
DEFAULT_SELECTED_FILE = None
DEFAULT_OPEN_FILES = [
    "ChatLayout.tsx",
    "MessageList.tsx",
    "TerminalPanel.tsx",
    "ToolPanel.tsx",
    "FilePreview.tsx",
]
STATE_DB_PATH = ROOT / ".supercode" / "state.sqlite3"
_session_store = SQLiteSessionStateAdapter(STATE_DB_PATH)

FILE_TREE_IGNORED_DIR_NAMES = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
FILE_TREE_MAX_DEPTH = 4
FILE_TREE_MAX_ENTRIES_PER_DIR = 200


class CreateSessionResponse(BaseModel):
    sessionId: str
    model: str
    modelId: str | None = None
    mode: str
    isGenerating: bool
    startupError: str | None
    envFile: str | None
    workspace: str
    workspaceOptions: list[dict[str, str]]
    messages: list[dict[str, Any]]
    toolCalls: list[dict[str, Any]]
    thoughts: list[str]
    terminalOutput: str
    previewUrl: str
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
    model: str | None = None
    env_file: str | None = None


class UIModelProviderPayload(BaseModel):
    id: str | None = None
    name: str
    baseUrl: str
    apiKey: str
    models: list[str] = Field(default_factory=list)
    provider: str | None = None


class ModelConfigPayload(BaseModel):
    providers: list[UIModelProviderPayload] = Field(default_factory=list)


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


class ContinueChatStreamRequest(BaseModel):
    session_id: str = Field(alias="session_id")
    assistant_id: str = Field(alias="assistant_id")


class TerminalInputRequest(BaseModel):
    command: str = ""
    submit: bool = True


class TerminalControlRequest(BaseModel):
    action: Literal["interrupt"]


class ToolConfirmationRequest(BaseModel):
    approved: bool


class TerminalSnapshotResponse(BaseModel):
    sessionId: str
    output: str
    revision: int
    isAlive: bool
    shell: str
    backend: str = "subprocess"
    cwd: str | None = None
    supportsInterrupt: bool = False
    supportsRawInput: bool = True
    fileTree: list[dict[str, Any]] | None = None
    processes: list[dict[str, Any]] | None = None


class ManagedProcessInfo(BaseModel):
    pid: int
    parent_pid: int
    name: str
    command_line: str
    is_root: bool


class ManagedProcessResponse(BaseModel):
    terminalId: str
    command: str
    rootPid: int
    status: str
    returnCode: int | None
    startedAt: int
    terminatedAt: int | None
    processCount: int
    processes: list[ManagedProcessInfo]


@dataclass
class TerminalRuntime:
    workspace: str
    shell: str = "powershell"
    output: str = ""
    revision: int = 0
    backend: str = field(default="subprocess", init=False)
    current_directory: str = field(default="", init=False)
    supports_interrupt: bool = field(default=False, init=False)
    supports_raw_input: bool = field(default=True, init=False)
    pty_process: Any | None = field(default=None, init=False, repr=False)
    process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    stdout_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    stderr_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    prompt_pattern: re.Pattern[str] = field(
        default=re.compile(r"(?m)^PS (?P<path>[^\r\n>]+)>"),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.current_directory = self.workspace
        if PtyProcess is not None:
            try:
                self._start_winpty()
                return
            except Exception:
                self.pty_process = None
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
        self.backend = "subprocess"
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_pipe_stream,
            args=(self.process.stdout,),
            daemon=True,
        )
        self.stderr_thread = threading.Thread(
            target=self._pump_pipe_stream,
            args=(self.process.stderr,),
            daemon=True,
        )
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _start_winpty(self) -> None:
        if PtyProcess is None:
            raise RuntimeError("winpty 不可用")
        command = self._build_powershell_command()
        self.pty_process = PtyProcess.spawn(command)
        self.backend = "winpty"
        self.supports_interrupt = True
        self.append_output(f"PowerShell started in {self.workspace}\n")
        self.stdout_thread = threading.Thread(
            target=self._pump_pty_stream,
            daemon=True,
        )
        self.stdout_thread.start()

    def _build_powershell_command(self) -> str:
        escaped_workspace = self.workspace.replace("'", "''")
        bootstrap = (
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "chcp 65001 > $null; "
            f"Set-Location -LiteralPath '{escaped_workspace}'"
        )
        return (
            "powershell "
            "-NoLogo "
            "-NoProfile "
            "-NoExit "
            "-ExecutionPolicy Bypass "
            f'-Command "{bootstrap}"'
        )

    def _pump_pty_stream(self) -> None:
        if self.pty_process is None:
            return
        try:
            while self.pty_process.isalive():
                chunk = self.pty_process.read(1024)
                if chunk == "":
                    break
                self.append_output(chunk)
        except EOFError:
            return
        except Exception:
            self.append_output("\n[terminal reader stopped unexpectedly]\n")

    def _pump_pipe_stream(self, stream: Any) -> None:
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
            inferred_cwd = self._infer_current_directory(self.output[-4096:])
            if inferred_cwd:
                self.current_directory = inferred_cwd
            self.revision += 1

    def _infer_current_directory(self, text: str) -> str | None:
        matches = list(self.prompt_pattern.finditer(text))
        if not matches:
            return None
        return matches[-1].group("path").strip()

    def send_input(self, content: str, submit: bool = True) -> None:
        payload = content
        if submit:
            payload += "\n"
        if payload == "":
            return
        if self.pty_process is not None:
            self.pty_process.write(payload)
            return
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("terminal process is not available")
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def write(self, command: str) -> None:
        self.send_input(command, submit=True)

    def interrupt(self) -> bool:
        if self.pty_process is None or not hasattr(self.pty_process, "sendcontrol"):
            return False
        self.pty_process.sendcontrol("c")
        return True

    def snapshot(self, session_id: str) -> TerminalSnapshotResponse:
        with self.lock:
            return TerminalSnapshotResponse(
                sessionId=session_id,
                output=self.output,
                revision=self.revision,
                isAlive=self.is_alive(),
                shell=self.shell,
                backend=self.backend,
                cwd=self.current_directory or self.workspace,
                supportsInterrupt=self.supports_interrupt,
                supportsRawInput=self.supports_raw_input,
            )

    def is_alive(self) -> bool:
        if self.pty_process is not None:
            return bool(self.pty_process.isalive())
        return self.process is not None and self.process.poll() is None

    def clear(self) -> None:
        with self.lock:
            self.output = ""
            self.revision += 1

    def close(self) -> None:
        if self.pty_process is not None:
            try:
                self.pty_process.write("exit\n")
            except Exception:
                pass
            try:
                self.pty_process.terminate(force=True)
            except Exception:
                pass
            self.pty_process = None
            return
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
    env_file: str | None = None
    selected_file_path: str | None = DEFAULT_SELECTED_FILE
    open_files: list[str] = field(default_factory=lambda: list(DEFAULT_OPEN_FILES))
    terminal_output: str = ""
    preview_url: str = DEFAULT_BROWSER_PREVIEW_URL
    terminal_runtime: TerminalRuntime | None = field(default=None, repr=False)
    interactive_command_session: InteractiveCommandSession | None = field(default=None, repr=False)
    chat_session: ChatSession | None = None
    is_generating: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    cached_file_tree: list[dict[str, Any]] = field(default_factory=list, repr=False)
    file_tree_loaded: bool = field(default=False, repr=False)
    file_tree_dirty: bool = field(default=True, repr=False)
    file_tree_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    pending_delete_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    pending_commit_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    pending_tag_confirmations: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
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
            modelId=resolve_model_reference_id(self.model, self.env_file),
            mode=self.mode,
            isGenerating=self.is_generating,
            startupError=self.startup_error,
            envFile=self.env_file,
            workspace=self.workspace,
            workspaceOptions=list_workspace_options(),
            messages=self.history_messages,
            toolCalls=self.history_tools,
            thoughts=self.thoughts,
            terminalOutput=self.terminal_output,
            previewUrl=self.preview_url,
            fileTree=self.get_file_tree(),
            selectedFilePath=self.selected_file_path,
            selectedFileContent=read_text_file(self.selected_file_path, self.workspace),
            openFiles=self.open_files,
            planSteps=self.plan_steps,
        )

    def mark_file_tree_dirty(self) -> None:
        with self.file_tree_lock:
            self.file_tree_dirty = True

    def get_file_tree(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        with self.file_tree_lock:
            if force_refresh or self.file_tree_dirty or not self.file_tree_loaded:
                self.cached_file_tree = build_file_tree(resolve_workspace_path(self.workspace))
                self.file_tree_loaded = True
                self.file_tree_dirty = False
            return self.cached_file_tree

    def get_managed_processes(self, active_only: bool = True) -> list[dict[str, Any]]:
        if self.interactive_command_session is None:
            return []
        return self.interactive_command_session.list_managed_processes(only_active=active_only)

    def terminal_snapshot(
        self,
        include_file_tree: bool = False,
        include_processes: bool = False,
    ) -> TerminalSnapshotResponse:
        if self.terminal_runtime is None:
            raise RuntimeError("terminal 不存在")
        snapshot = self.terminal_runtime.snapshot(self.session_id)
        self.terminal_output = snapshot.output
        return TerminalSnapshotResponse(
            sessionId=snapshot.sessionId,
            output=snapshot.output,
            revision=snapshot.revision,
            isAlive=snapshot.isAlive,
            shell=snapshot.shell,
            backend=snapshot.backend,
            cwd=snapshot.cwd,
            supportsInterrupt=snapshot.supportsInterrupt,
            supportsRawInput=snapshot.supportsRawInput,
            fileTree=self.get_file_tree() if include_file_tree else None,
            processes=self.get_managed_processes(active_only=True) if include_processes else None,
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
        persist_session_state(self)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    def _cleanup_sessions() -> None:
        for session in _sessions.values():
            stop_session_execution(session)
            if session.terminal_runtime is not None:
                session.terminal_runtime.close()
            if session.interactive_command_session is not None:
                session.interactive_command_session.close()

    yield

    _cleanup_sessions()


app = FastAPI(title="SuperCode Agent UI API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, UISession] = {}


def session_has_persistable_history(session: UISession) -> bool:
    if session.history_messages:
        return True
    if session.history_tools:
        return True
    if session.thoughts:
        return True
    return False


def persist_session_state(session: UISession) -> None:
    if not session_has_persistable_history(session):
        try:
            _session_store.delete(session.session_id)
        except Exception:
            pass
        return
    try:
        _session_store.save(session_to_persisted_state(session))
    except Exception:
        # Persistence must not interrupt the streaming path.
        pass


def set_session_generating(session: UISession, is_generating: bool) -> None:
    if session.is_generating == is_generating:
        return
    session.is_generating = is_generating
    session.touch()


def session_to_persisted_state(session: UISession) -> PersistedSessionState:
    return PersistedSessionState(
        session_id=session.session_id,
        workspace=session.workspace,
        mode=session.mode,
        model=session.model,
        title=session.summary_title(),
        preview=session.summary_preview(),
        message_count=len(session.history_messages),
        tool_call_count=len(session.history_tools),
        created_at=session.created_at,
        updated_at=session.updated_at,
        is_generating=session.is_generating,
        startup_error=session.startup_error,
        env_file=session.env_file,
        selected_file_path=session.selected_file_path,
        open_files=session.open_files,
        terminal_output=session.terminal_output,
        preview_url=session.preview_url,
        history_messages=session.history_messages,
        history_tools=session.history_tools,
        thoughts=session.thoughts,
        plan_steps=session.plan_steps,
        pending_delete_confirmations=session.pending_delete_confirmations,
        pending_commit_confirmations=session.pending_commit_confirmations,
        pending_tag_confirmations=session.pending_tag_confirmations,
    )


def persisted_state_to_history_item(state: PersistedSessionState) -> SessionHistoryItem:
    return SessionHistoryItem(
        sessionId=state.session_id,
        workspace=state.workspace,
        mode=state.mode,
        model=state.model,
        title=state.title,
        preview=state.preview,
        messageCount=state.message_count,
        toolCallCount=state.tool_call_count,
        createdAt=state.created_at,
        updatedAt=state.updated_at,
    )


def hydrate_session_from_state(state: PersistedSessionState) -> UISession:
    chat_session, model_name, startup_error, env_file_used = build_chat_session(
        state.workspace,
        state.env_file,
    )
    interactive_command_session = InteractiveCommandSession(
        workspace=resolve_workspace_path(state.workspace)
    )
    session = UISession(
        session_id=state.session_id,
        model=model_name if chat_session is not None else state.model,
        workspace=state.workspace,
        mode="agent" if chat_session is not None else state.mode,
        is_generating=state.is_generating,
        startup_error=startup_error if chat_session is None else state.startup_error,
        env_file=env_file_used or state.env_file,
        selected_file_path=state.selected_file_path,
        open_files=state.open_files,
        terminal_output=state.terminal_output,
        preview_url=state.preview_url or DEFAULT_BROWSER_PREVIEW_URL,
        terminal_runtime=TerminalRuntime(workspace=state.workspace),
        interactive_command_session=interactive_command_session,
        chat_session=chat_session,
        history_messages=state.history_messages,
        history_tools=state.history_tools,
        thoughts=state.thoughts,
        created_at=state.created_at,
        updated_at=state.updated_at,
        plan_steps=state.plan_steps,
        pending_delete_confirmations=state.pending_delete_confirmations,
        pending_commit_confirmations=state.pending_commit_confirmations,
        pending_tag_confirmations=state.pending_tag_confirmations,
    )
    if session.chat_session is not None:
        seed_chat_session_history(session.chat_session, state.history_messages)
    if session.chat_session is not None and isinstance(session.chat_session.agent, CodingAgent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
        )
    return session


def ensure_user_message_recorded(session: UISession, user_message: str) -> None:
    cleaned_message = user_message.strip()
    if not cleaned_message:
        return
    last_message = session.history_messages[-1] if session.history_messages else None
    if (
        isinstance(last_message, dict)
        and last_message.get("role") == "user"
        and str(last_message.get("content", "")).strip() == cleaned_message
    ):
        return
    session.history_messages.append(
        {"id": uuid.uuid4().hex, "role": "user", "content": cleaned_message}
    )
    session.touch()


def update_assistant_history_message(
    session: UISession,
    assistant_id: str,
    updater: Any,
) -> None:
    current_message = next(
        (
            message
            for message in session.history_messages
            if message.get("id") == assistant_id and message.get("role") == "assistant"
        ),
        None,
    )
    base_message = (
        {**current_message}
        if isinstance(current_message, dict)
        else {
            "id": assistant_id,
            "role": "assistant",
            "content": "",
            "thoughts": "",
            "toolCalls": [],
            "parts": [],
        }
    )
    next_message = updater(base_message)
    session.history_messages = upsert_message(session.history_messages, next_message)
    session.touch()


def sync_assistant_message_fields(message: dict[str, Any]) -> dict[str, Any]:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return message

    text_parts = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    thinking_parts = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "thinking" and str(part.get("text") or "").strip()
    ]
    tool_calls = [
        part.get("toolCall")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "tool_call" and isinstance(part.get("toolCall"), dict)
    ]
    return {
        **message,
        "content": "".join(text_parts),
        "thoughts": "\n\n".join(thinking_parts),
        "toolCalls": tool_calls,
    }


def append_assistant_part_delta(
    session: UISession,
    assistant_id: str,
    part_type: str,
    delta: str,
) -> None:
    if not delta:
        return

    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        last_part = parts[-1] if parts else None
        if isinstance(last_part, dict) and last_part.get("type") == part_type:
            parts[-1] = {**last_part, "text": f"{str(last_part.get('text') or '')}{delta}"}
        else:
            parts.append({"type": part_type, "text": delta})
        return sync_assistant_message_fields({**message, "parts": parts})

    update_assistant_history_message(session, assistant_id, _updater)


def upsert_assistant_thinking_part(
    session: UISession,
    assistant_id: str,
    thought_text: str,
) -> None:
    if not thought_text.strip():
        return

    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            if not isinstance(part, dict) or part.get("type") != "thinking":
                continue
            existing_text = str(part.get("text") or "")
            if thought_text.startswith(existing_text) or existing_text.startswith(thought_text):
                parts[index] = {**part, "text": thought_text}
                return sync_assistant_message_fields({**message, "parts": parts})
            break
        parts.append({"type": "thinking", "text": thought_text})
        return sync_assistant_message_fields({**message, "parts": parts})

    update_assistant_history_message(session, assistant_id, _updater)


def replace_assistant_text_part(
    session: UISession,
    assistant_id: str,
    text: str,
) -> None:
    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = [
            part
            for part in list(message.get("parts") or [])
            if not (isinstance(part, dict) and part.get("type") == "text")
        ]
        if text:
            parts.append({"type": "text", "text": text})
        return sync_assistant_message_fields({**message, "parts": parts})

    update_assistant_history_message(session, assistant_id, _updater)


def clear_assistant_text_part(session: UISession, assistant_id: str) -> None:
    replace_assistant_text_part(session, assistant_id, "")


def append_assistant_tool_call(
    session: UISession,
    assistant_id: str,
    tool_call: dict[str, Any],
) -> None:
    tool_id = str(tool_call.get("id") or "").strip()
    if not tool_id:
        return

    def _updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        replaced = False
        next_parts: list[dict[str, Any]] = []
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") == "tool_call"
                and isinstance(part.get("toolCall"), dict)
                and str(part["toolCall"].get("id") or "") == tool_id
            ):
                next_parts.append({"type": "tool_call", "toolCall": {**part["toolCall"], **tool_call}})
                replaced = True
            else:
                next_parts.append(part)
        if not replaced:
            next_parts.append({"type": "tool_call", "toolCall": tool_call})
        return sync_assistant_message_fields({**message, "parts": next_parts})

    update_assistant_history_message(session, assistant_id, _updater)


def update_assistant_tool_call(
    session: UISession,
    assistant_id: str,
    tool_id: str,
    updater: Any,
) -> None:
    def _message_updater(message: dict[str, Any]) -> dict[str, Any]:
        parts = list(message.get("parts") or [])
        next_parts: list[dict[str, Any]] = []
        found = False
        for part in parts:
            if (
                isinstance(part, dict)
                and part.get("type") == "tool_call"
                and isinstance(part.get("toolCall"), dict)
                and str(part["toolCall"].get("id") or "") == tool_id
            ):
                next_parts.append({"type": "tool_call", "toolCall": updater({**part["toolCall"]})})
                found = True
            else:
                next_parts.append(part)
        if not found:
            next_parts.append({"type": "tool_call", "toolCall": updater({"id": tool_id})})
        return sync_assistant_message_fields({**message, "parts": next_parts})

    update_assistant_history_message(session, assistant_id, _message_updater)


def seed_chat_session_history(
    chat_session: ChatSession,
    history_messages: list[dict[str, Any]],
) -> None:
    chat_session.state.conversation_messages = [
        ConversationMessage(
            role=str(message.get("role", "")),
            content=str(message.get("content", "")),
        )
        for message in history_messages
        if str(message.get("role", "")) in {"user", "assistant", "system"}
        and str(message.get("content", "")).strip()
    ]


def record_confirmation_result_for_agent(session: UISession, content: str) -> None:
    if session.chat_session is None:
        return
    text = content.strip()
    if not text:
        return
    session.chat_session.state.conversation_messages.append(
        ConversationMessage(role="system", content=text)
    )


def stop_session_execution(session: UISession) -> list[dict[str, Any]]:
    """停止当前会话里由 AI 工具托管的命令进程。"""

    session.cancel_event.set()
    interactive_session = session.interactive_command_session
    if interactive_session is None:
        set_session_generating(session, False)
        return []
    terminated = interactive_session.terminate_all()
    set_session_generating(session, False)
    return terminated


@app.get("/api/workspaces")
async def get_workspaces() -> JSONResponse:
    return JSONResponse({"workspaces": list_workspace_options()})


@app.get("/api/models")
async def get_models() -> JSONResponse:
    return JSONResponse({"models": list_model_options(ROOT)})


@app.get("/api/model-configs")
async def get_model_configs() -> JSONResponse:
    return JSONResponse(
        {
            "providers": load_ui_model_providers(ROOT),
            "envConfigs": scan_env_model_sources(ROOT),
            "configPath": str(config_store_path(ROOT)),
        }
    )


@app.put("/api/model-configs")
async def update_model_configs(payload: ModelConfigPayload) -> JSONResponse:
    providers = save_ui_model_providers(
        ROOT,
        [provider.model_dump(exclude_none=True) for provider in payload.providers],
    )
    return JSONResponse(
        {
            "providers": providers,
            "envConfigs": scan_env_model_sources(ROOT),
            "configPath": str(config_store_path(ROOT)),
        }
    )


@app.post("/api/model-configs/discover-models")
async def discover_models(payload: UIModelProviderPayload) -> JSONResponse:
    try:
        models = await asyncio.to_thread(
            discover_provider_models,
            payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"models": models})


class SwitchModelRequest(BaseModel):
    model: str | None = None
    env_file: str | None = None


@app.put("/api/sessions/{session_id}/model")
async def switch_session_model(session_id: str, request: SwitchModelRequest) -> JSONResponse:
    session = require_session(session_id)
    model_option = resolve_model_option(request.model, request.env_file)
    model_ref = model_option["envFile"]

    try:
        config, normalized_model_ref = build_agent_config(ROOT, model_ref)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = OpenAICompatibleClient(config)
    agent = CodingAgent(
        brain=CodingPromptBrain(client, workspace=session.workspace),
        tools=build_coding_tools(),
        workspace=resolve_workspace_path(session.workspace),
        tool_context_metadata={
            "include_thoughts_in_context": config.include_thoughts_in_context,
        },
    )
    interactive_command_session = session.interactive_command_session

    session.chat_session = ChatSession(agent=agent)
    seed_chat_session_history(session.chat_session, session.history_messages)
    if isinstance(session.chat_session.agent, CodingAgent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            include_thoughts_in_context=config.include_thoughts_in_context,
        )
    session.model = config.model
    session.env_file = normalized_model_ref
    session.mode = "agent"
    session.startup_error = None
    session.touch()

    return JSONResponse({
        "model": session.model,
        "modelId": resolve_model_reference_id(session.model, session.env_file),
        "mode": session.mode,
        "envFile": session.env_file,
        "previewUrl": session.preview_url,
    })


@app.get("/api/directories")
async def get_directories(path: str = Query(...)) -> JSONResponse:
    root = normalize_workspace(path)
    return JSONResponse({"path": str(root), "children": list_child_directories(root)})


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest) -> JSONResponse:
    session_id = uuid.uuid4().hex
    workspace = normalize_workspace(request.workspace)
    requested_env_file = resolve_requested_env_file(request.model, request.env_file)

    try:
        chat_session, model_name, startup_error, env_file_used = await asyncio.wait_for(
            asyncio.to_thread(build_chat_session, workspace, requested_env_file),
            timeout=30,
        )
    except asyncio.TimeoutError:
        chat_session, model_name, startup_error, env_file_used = None, "Demo", "初始化模型超时", None

    interactive_command_session = InteractiveCommandSession(
        workspace=resolve_workspace_path(workspace)
    )

    workspace_path = resolve_workspace_path(workspace)
    if not (workspace_path / ".git").exists():
        try:
            await asyncio.to_thread(init_git_repo, workspace_path)
        except Exception:
            pass

    session = UISession(
        session_id=session_id,
        model=model_name,
        workspace=workspace,
        env_file=env_file_used,
        terminal_runtime=TerminalRuntime(workspace=workspace),
        interactive_command_session=interactive_command_session,
        chat_session=chat_session,
        mode="agent" if chat_session is not None else "demo",
        startup_error=startup_error,
        selected_file_path=pick_default_file(workspace),
        open_files=build_default_open_files(workspace),
    )
    if session.chat_session is not None and isinstance(session.chat_session.agent, CodingAgent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
        )
    _sessions[session_id] = session
    persist_session_state(session)

    try:
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(session.snapshot),
            timeout=15,
        )
    except asyncio.TimeoutError:
        snapshot = CreateSessionResponse(
            sessionId=session.session_id,
            model=session.model,
            mode=session.mode,
            isGenerating=session.is_generating,
            startupError=session.startup_error,
            envFile=session.env_file,
            workspace=session.workspace,
            workspaceOptions=list_workspace_options(),
            messages=session.history_messages,
            toolCalls=session.history_tools,
            thoughts=session.thoughts,
            terminalOutput=session.terminal_output,
            previewUrl=session.preview_url,
            fileTree=[],
            selectedFilePath=session.selected_file_path,
            selectedFileContent="",
            openFiles=session.open_files,
            planSteps=session.plan_steps,
        )
    return JSONResponse(snapshot.model_dump())


@app.get("/api/sessions/history")
async def get_session_history() -> JSONResponse:
    history = [persisted_state_to_history_item(state).model_dump() for state in _session_store.list()]
    return JSONResponse({"sessions": history})


@app.get("/api/sessions/{session_id}")
async def get_session_snapshot(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    try:
        snapshot = await asyncio.wait_for(asyncio.to_thread(session.snapshot), timeout=15)
    except asyncio.TimeoutError:
        snapshot = CreateSessionResponse(
            sessionId=session.session_id,
            model=session.model,
            mode=session.mode,
            isGenerating=session.is_generating,
            startupError=session.startup_error,
            envFile=session.env_file,
            workspace=session.workspace,
            workspaceOptions=list_workspace_options(),
            messages=session.history_messages,
            toolCalls=session.history_tools,
            thoughts=session.thoughts,
            terminalOutput=session.terminal_output,
            previewUrl=session.preview_url,
            fileTree=[],
            selectedFilePath=session.selected_file_path,
            selectedFileContent="",
            openFiles=session.open_files,
            planSteps=session.plan_steps,
        )
    return JSONResponse(snapshot.model_dump())


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    session = _sessions.pop(session_id, None)
    if session is None:
        if _session_store.load(session_id) is None:
            raise HTTPException(status_code=404, detail="session 不存在")
    else:
        stop_session_execution(session)
        if session.terminal_runtime is not None:
            session.terminal_runtime.close()
        if session.interactive_command_session is not None:
            session.interactive_command_session.close()
    _session_store.delete(session_id)
    return JSONResponse({"deleted": True, "sessionId": session_id})


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    terminated = stop_session_execution(session)
    remaining = (
        session.interactive_command_session.list_managed_processes(only_active=True)
        if session.interactive_command_session is not None
        else []
    )
    return JSONResponse(
        {
            "stopped": True,
            "terminatedCount": len(terminated),
            "terminated": terminated,
            "remaining": remaining,
        }
    )


@app.get("/api/sessions/{session_id}/processes")
async def get_session_processes(
    session_id: str,
    active_only: bool = Query(True),
) -> JSONResponse:
    session = require_session(session_id)
    interactive_session = session.interactive_command_session
    if interactive_session is None:
        return JSONResponse({"processes": []})
    processes = interactive_session.list_managed_processes(only_active=active_only)
    return JSONResponse({"processes": processes})


@app.post("/api/sessions/{session_id}/processes/{terminal_id}/terminate")
async def terminate_session_process(session_id: str, terminal_id: str) -> JSONResponse:
    session = require_session(session_id)
    interactive_session = session.interactive_command_session
    if interactive_session is None:
        raise HTTPException(status_code=404, detail="当前会话没有受管进程")
    try:
        result = interactive_session.terminate_command(terminal_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.touch()
    return JSONResponse({"terminated": True, "process": result})


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


@app.get("/api/sessions/{session_id}/preview")
@app.get("/api/sessions/{session_id}/preview/{preview_path:path}")
async def preview_session_file(session_id: str, preview_path: str = "") -> FileResponse:
    session = require_session(session_id)
    target = resolve_preview_path(preview_path, session.workspace)
    return FileResponse(target)


@app.get("/api/sessions/{session_id}/file-tree")
async def get_file_tree(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    try:
        tree = await asyncio.wait_for(asyncio.to_thread(session.get_file_tree), timeout=15)
    except asyncio.TimeoutError:
        tree = []
    return JSONResponse(
        {
            "fileTree": tree,
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
        session.mark_file_tree_dirty()
        session.touch()
        return JSONResponse({"saved": True, "path": resolved_path})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-delete")
async def confirm_delete_tool(
    session_id: str,
    tool_id: str,
    request: ToolConfirmationRequest,
) -> JSONResponse:
    session = require_session(session_id)
    pending = session.pending_delete_confirmations.pop(tool_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="未找到待确认的删除动作")

    filename = str(pending.get("filename") or "").strip()
    assistant_id = str(pending.get("assistant_id") or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="待确认删除动作缺少 filename")

    approval = {"id": tool_id, "approved": request.approved}
    assistant_id = str(pending.get("assistant_id") or "").strip()
    if not request.approved:
        tool_record = {
            "id": tool_id,
            "output": "已取消删除。",
            "success": False,
            "state": "output-denied",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 已取消：{filename}")
        session.touch()
        return JSONResponse(
            {
                "id": tool_id,
                "name": "delete_file",
                "output": "已取消删除。",
                "success": False,
                "state": "output-denied",
                "approval": approval,
                "selectedFileCleared": False,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            }
        )

    selected_file_cleared = False
    try:
        output = delete_file_in_workspace(filename, resolve_workspace_path(session.workspace))
        session.mark_file_tree_dirty()
        if session.selected_file_path == normalize_relative_path(filename, session.workspace):
            session.selected_file_path = None
            selected_file_cleared = True
        tool_record = {
            "id": tool_id,
            "output": output,
            "success": True,
            "state": "output-available",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 已确认并执行成功：{output}")
        session.touch()
        return JSONResponse(
            {
                "id": tool_id,
                "name": "delete_file",
                "output": output,
                "success": True,
                "state": "output-available",
                "approval": approval,
                "selectedFileCleared": selected_file_cleared,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            }
        )
    except Exception as exc:
        tool_record = {
            "id": tool_id,
            "output": None,
            "success": False,
            "state": "error",
            "errorMessage": str(exc),
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] delete_file 执行失败：{exc}")
        session.touch()
        return JSONResponse(
            {
                "id": tool_id,
                "name": "delete_file",
                "output": None,
                "success": False,
                "state": "error",
                "error_message": str(exc),
                "approval": approval,
                "selectedFileCleared": False,
                "assistantId": assistant_id,
                "shouldContinue": bool(assistant_id),
            },
            status_code=500,
        )


class GitCommitRequest(BaseModel):
    message: str


class GitTagRequest(BaseModel):
    tag: str
    message: str | None = None


@app.post("/api/sessions/{session_id}/git/init")
async def git_init(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    try:
        output = await asyncio.to_thread(init_git_repo, workspace)
        session.mark_file_tree_dirty()
        session.touch()
        return JSONResponse({"success": True, "output": output})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/api/sessions/{session_id}/git/log")
async def git_log(session_id: str, count: int = Query(20)) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    if not (workspace / ".git").exists():
        return JSONResponse({"commits": [], "isRepo": False})
    try:
        safe_count = min(max(count, 1), 100)
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "log", f"-{safe_count}", "--pretty=format:%h|%an|%ai|%s"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            return JSONResponse({"commits": [], "isRepo": True, "error": result.stderr.strip()})

        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 3)
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })

        status_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "status", "--porcelain"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        changed_files = [l.strip() for l in status_result.stdout.strip().splitlines() if l.strip()] if status_result.stdout.strip() else []

        branch_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

        return JSONResponse({
            "commits": commits,
            "isRepo": True,
            "changedFiles": changed_files,
            "branch": branch,
        })
    except Exception as exc:
        return JSONResponse({"commits": [], "isRepo": True, "error": str(exc)}, status_code=500)


@app.post("/api/sessions/{session_id}/git/commit")
async def git_commit(session_id: str, request: GitCommitRequest) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="提交信息不能为空")
    try:
        output = await asyncio.to_thread(execute_git_commit, message, workspace)
        session.mark_file_tree_dirty()
        session.touch()
        return JSONResponse({"success": True, "output": output})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.post("/api/sessions/{session_id}/git/tag")
async def git_tag(session_id: str, request: GitTagRequest) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    tag_name = request.tag.strip()
    if not tag_name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    tag_message = request.message or f"Release {tag_name}"
    try:
        output = await asyncio.to_thread(execute_git_tag, tag_name, tag_message, workspace)
        session.touch()
        return JSONResponse({"success": True, "output": output})
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@app.get("/api/sessions/{session_id}/git/tags")
async def git_tags(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    if not (workspace / ".git").exists():
        return JSONResponse({"tags": [], "isRepo": False})
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "tag", "-l", "--sort=-creatordate", "--format=%(refname:short)|%(creatordate:short)|%(subject)"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        tags = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            tags.append({
                "name": parts[0],
                "date": parts[1] if len(parts) > 1 else "",
                "message": parts[2] if len(parts) > 2 else "",
            })
        return JSONResponse({"tags": tags, "isRepo": True})
    except Exception as exc:
        return JSONResponse({"tags": [], "isRepo": True, "error": str(exc)}, status_code=500)


@app.get("/api/sessions/{session_id}/git/status")
async def git_status(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    workspace = resolve_workspace_path(session.workspace)
    if not (workspace / ".git").exists():
        return JSONResponse({"isRepo": False, "changedFiles": [], "branch": ""})
    try:
        status_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "status", "--porcelain"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        changed_files = [l.strip() for l in status_result.stdout.strip().splitlines() if l.strip()] if status_result.stdout.strip() else []

        branch_result = await asyncio.to_thread(
            subprocess.run,
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

        return JSONResponse({"isRepo": True, "changedFiles": changed_files, "branch": branch})
    except Exception as exc:
        return JSONResponse({"isRepo": True, "changedFiles": [], "branch": "", "error": str(exc)}, status_code=500)


@app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-commit")
async def confirm_commit_tool(
    session_id: str,
    tool_id: str,
    request: ToolConfirmationRequest,
) -> JSONResponse:
    session = require_session(session_id)
    pending = session.pending_commit_confirmations.pop(tool_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="未找到待确认的提交动作")

    approval = {"id": tool_id, "approved": request.approved}
    assistant_id = str(pending.get("assistant_id") or "").strip()
    if not request.approved:
        tool_record = {
            "id": tool_id,
            "output": "已取消提交。",
            "success": False,
            "state": "output-denied",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, "[内部确认结果] git_commit 已取消。")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_commit",
            "output": "已取消提交。",
            "success": False,
            "state": "output-denied",
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        })

    commit_message = str(pending.get("commit_message") or "")
    if not commit_message:
        raise HTTPException(status_code=400, detail="待确认提交动作缺少 commit_message")

    try:
        output = execute_git_commit(commit_message, resolve_workspace_path(session.workspace))
        session.mark_file_tree_dirty()
        tool_record = {
            "id": tool_id,
            "output": output,
            "success": True,
            "state": "output-available",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] git_commit 已确认并执行成功：{output}")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_commit",
            "output": output,
            "success": True,
            "state": "output-available",
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        })
    except Exception as exc:
        tool_record = {
            "id": tool_id,
            "output": None,
            "success": False,
            "state": "error",
            "errorMessage": str(exc),
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] git_commit 执行失败：{exc}")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_commit",
            "output": None,
            "success": False,
            "state": "error",
            "error_message": str(exc),
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        }, status_code=500)


@app.post("/api/sessions/{session_id}/tools/{tool_id}/confirm-tag")
async def confirm_tag_tool(
    session_id: str,
    tool_id: str,
    request: ToolConfirmationRequest,
) -> JSONResponse:
    session = require_session(session_id)
    pending = session.pending_tag_confirmations.pop(tool_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="未找到待确认的标签动作")

    approval = {"id": tool_id, "approved": request.approved}
    if not request.approved:
        tool_record = {
            "id": tool_id,
            "output": "已取消创建标签。",
            "success": False,
            "state": "output-denied",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, "[内部确认结果] git_tag 已取消。")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_tag",
            "output": "已取消创建标签。",
            "success": False,
            "state": "output-denied",
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        })

    tag_name = str(pending.get("tag") or "")
    tag_message = str(pending.get("tag_message") or f"Release {tag_name}")
    if not tag_name:
        raise HTTPException(status_code=400, detail="待确认标签动作缺少 tag")

    try:
        output = execute_git_tag(tag_name, tag_message, resolve_workspace_path(session.workspace))
        tool_record = {
            "id": tool_id,
            "output": output,
            "success": True,
            "state": "output-available",
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] git_tag 已确认并执行成功：{output}")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_tag",
            "output": output,
            "success": True,
            "state": "output-available",
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        })
    except Exception as exc:
        tool_record = {
            "id": tool_id,
            "output": None,
            "success": False,
            "state": "error",
            "errorMessage": str(exc),
            "approval": approval,
        }
        session.history_tools = upsert_tool(session.history_tools, tool_record)
        record_confirmation_result_for_agent(session, f"[内部确认结果] git_tag 执行失败：{exc}")
        session.touch()
        return JSONResponse({
            "id": tool_id,
            "name": "git_tag",
            "output": None,
            "success": False,
            "state": "error",
            "error_message": str(exc),
            "approval": approval,
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
        }, status_code=500)


@app.get("/api/sessions/{session_id}/context")
async def get_session_context(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(session.context_snapshot().model_dump())


@app.get("/api/sessions/{session_id}/terminal")
async def get_session_terminal(
    session_id: str,
    include_file_tree: bool = Query(False),
    include_processes: bool = Query(False),
) -> JSONResponse:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    snapshot = session.terminal_snapshot(
        include_file_tree=include_file_tree,
        include_processes=include_processes,
    )
    return JSONResponse(snapshot.model_dump())


@app.post("/api/sessions/{session_id}/terminal/input")
async def post_session_terminal_input(
    session_id: str,
    request: TerminalInputRequest,
) -> JSONResponse:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    if request.command == "" and not request.submit:
        raise HTTPException(status_code=400, detail="command 和 submit 不能同时为空")
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
    session = require_session(session_id)
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
    session = require_session(session_id)
    if session.terminal_runtime is None:
        raise HTTPException(status_code=404, detail="terminal 不存在")
    session.terminal_runtime.clear()
    snapshot = session.terminal_runtime.snapshot(session_id)
    session.terminal_output = snapshot.output
    return JSONResponse(snapshot.model_dump())


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatStreamRequest,
    protocol: str = Query("ui-message"),
) -> StreamingResponse:
    session = require_session(request.session_id)
    session.cancel_event.clear()
    user_message = request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        ui_adapter = UIMessageStreamAdapter()
        ui_finished = False
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
                if protocol == "legacy":
                    yield sse_data(event)
                    continue

                for part in ui_adapter.convert(event):
                    if part.get("type") == "finish":
                        ui_finished = True
                    yield sse_data(part)
                    if part.get("type") == "tool-input-delta":
                        await asyncio.sleep(0.01)

            if protocol != "legacy" and not ui_finished:
                for part in ui_adapter.finish_if_needed():
                    yield sse_data(part)
            if protocol != "legacy":
                yield sse_data("[DONE]")
        except asyncio.CancelledError:
            stop_session_execution(session)
            raise
        finally:
            if producer.done():
                await producer
            else:
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer

    if protocol == "legacy":
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
        },
    )


@app.post("/api/chat/continue")
async def chat_continue(
    request: ContinueChatStreamRequest,
    protocol: str = Query("ui-message"),
) -> StreamingResponse:
    session = require_session(request.session_id)
    session.cancel_event.clear()
    assistant_id = request.assistant_id.strip()
    if not assistant_id:
        raise HTTPException(status_code=400, detail="assistant_id 不能为空")

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        ui_adapter = UIMessageStreamAdapter()
        ui_finished = False

        producer = asyncio.create_task(
            run_agent_stream(session, None, queue, assistant_id=assistant_id, resume_existing_turn=True)
        )

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if protocol == "legacy":
                    yield sse_data(event)
                    continue

                for part in ui_adapter.convert(event):
                    if part.get("type") == "finish":
                        ui_finished = True
                    yield sse_data(part)
                    if part.get("type") == "tool-input-delta":
                        await asyncio.sleep(0.01)

            if protocol != "legacy" and not ui_finished:
                for part in ui_adapter.finish_if_needed():
                    yield sse_data(part)
            if protocol != "legacy":
                yield sse_data("[DONE]")
        except asyncio.CancelledError:
            stop_session_execution(session)
            raise
        finally:
            if producer.done():
                await producer
            else:
                producer.cancel()
                with suppress(asyncio.CancelledError):
                    await producer

    if protocol == "legacy":
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
        },
    )


def require_session(session_id: str) -> UISession:
    session = _sessions.get(session_id)
    if session is None:
        persisted_state = _session_store.load(session_id)
        if persisted_state is None:
            raise HTTPException(status_code=404, detail="session 不存在")
        session = hydrate_session_from_state(persisted_state)
        _sessions[session_id] = session
    return session


def resolve_model_option(model_name: str | None, env_file: str | None = None) -> dict[str, str]:
    try:
        return resolve_stored_model_option(ROOT, model_name, env_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_model_reference_id(model_name: str | None, env_file: str | None = None) -> str | None:
    try:
        if env_file:
            return resolve_model_option(None, env_file)["id"]
        return resolve_model_option(model_name, None)["id"]
    except (HTTPException, KeyError):
        return env_file or model_name


def resolve_requested_env_file(model_name: str | None, env_file: str | None = None) -> str | None:
    if model_name or env_file:
        return resolve_model_option(model_name, env_file)["envFile"]
    return None


def attach_agent_runtime_metadata(
    agent: CodingAgent,
    session_id: str,
    interactive_command_session: InteractiveCommandSession | None,
    cancel_event: threading.Event | None = None,
    include_thoughts_in_context: bool | None = None,
) -> None:
    agent.tool_context_metadata["session_id"] = session_id
    agent.tool_context_metadata["backend_base_url"] = BACKEND_BASE_URL
    if include_thoughts_in_context is not None:
        agent.tool_context_metadata["include_thoughts_in_context"] = include_thoughts_in_context
    if interactive_command_session is not None:
        agent.tool_context_metadata["interactive_command_session"] = interactive_command_session
    if cancel_event is not None:
        agent.tool_context_metadata["cancel_event"] = cancel_event


def build_chat_session(workspace: str, env_file: str | None = None) -> tuple[ChatSession | None, str, str | None, str | None]:
    try:
        config, normalized_model_ref = build_agent_config(ROOT, env_file)
        client = OpenAICompatibleClient(config)
        agent = CodingAgent(
            brain=CodingPromptBrain(client, workspace=workspace),
            tools=build_coding_tools(),
            workspace=resolve_workspace_path(workspace),
            tool_context_metadata={
                "include_thoughts_in_context": config.include_thoughts_in_context,
            },
        )
        return ChatSession(agent=agent), config.model, None, normalized_model_ref
    except Exception as exc:  # noqa: BLE001 - 需要把启动失败原因回传给前端
        return None, "Demo", str(exc), None


async def run_agent_stream(
    session: UISession,
    user_message: str | None,
    queue: asyncio.Queue[dict[str, Any] | None],
    assistant_id: str | None = None,
    resume_existing_turn: bool = False,
) -> None:
    loop = asyncio.get_running_loop()
    assistant_id = assistant_id or uuid.uuid4().hex
    streamed_assistant_text = ""
    assistant_stream_started = False
    if user_message is not None:
        ensure_user_message_recorded(session, user_message)
    set_session_generating(session, True)

    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )
    update_assistant_history_message(session, assistant_id, lambda message: sync_assistant_message_fields(message))

    def on_event(event: AgentEvent) -> None:
        nonlocal streamed_assistant_text, assistant_stream_started

        if session.cancel_event.is_set():
            return

        if event.type == "thought_delta" and event.delta:
            append_assistant_part_delta(session, assistant_id, "thinking", event.delta)
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
                upsert_assistant_thinking_part(session, assistant_id, thought_text)
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
            append_assistant_part_delta(session, assistant_id, "text", event.delta)
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
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": tool_id,
                    "stepIndex": event.step_index,
                    "name": event.tool_call.name,
                    "arguments": event.tool_call.arguments,
                    "state": "running",
                },
            )
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

        if event.type == "tool_input_started" and event.tool_call is not None:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_input_started",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "arguments": event.tool_call.arguments,
                    },
                },
            )
            return

        if event.type == "tool_input_delta" and event.tool_call is not None and event.delta:
            tool_id = event.tool_call.id or f"step-{event.step_index}-{event.tool_call.name}"
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {
                    "type": "tool_input_delta",
                    "payload": {
                        "assistant_id": assistant_id,
                        "id": tool_id,
                        "step_index": event.step_index,
                        "name": event.tool_call.name,
                        "delta": event.delta,
                    },
                },
            )
            return

        if event.type == "tool_result" and event.tool_call is not None and event.tool_result is not None:
            tool_id = event.tool_call.id or event.tool_result.tool_call_id or f"step-{event.step_index}-{event.tool_call.name}"
            output = event.tool_result.output
            terminal_output = extract_terminal_output(output)
            preview_url = extract_preview_url(output)
            requires_confirmation = bool(
                (event.tool_result.name == "delete_file"
                 or event.tool_result.name == "git_commit"
                 or event.tool_result.name == "git_tag")
                and isinstance(output, dict)
                and output.get("requires_confirmation") is True
            )
            if event.tool_result.name in {"execute", "excecute", "terminal_input", "terminal_wait"} and terminal_output is not None:
                session.terminal_output = terminal_output
            if event.tool_result.name in {"write_file", "replace_file", "apply_patch"} or (
                event.tool_result.name == "delete_file" and not requires_confirmation
            ):
                session.mark_file_tree_dirty()
            if event.tool_result.name == "open_browser" and preview_url is not None:
                session.preview_url = preview_url
            tool_state = "approval-requested" if requires_confirmation else ("completed" if event.tool_result.success else "error")
            tool_success: bool | None = None if requires_confirmation else event.tool_result.success
            approval = {"id": tool_id} if requires_confirmation else None
            if requires_confirmation and isinstance(output, dict):
                if event.tool_result.name == "delete_file":
                    session.pending_delete_confirmations[tool_id] = {
                        "filename": str(output.get("filename") or ""),
                        "assistant_id": assistant_id,
                    }
                elif event.tool_result.name == "git_commit":
                    session.pending_commit_confirmations[tool_id] = {
                        "commit_message": str(output.get("commit_message") or ""),
                        "assistant_id": assistant_id,
                    }
                elif event.tool_result.name == "git_tag":
                    session.pending_tag_confirmations[tool_id] = {
                        "tag": str(output.get("tag") or ""),
                        "tag_message": str(output.get("tag_message") or ""),
                        "assistant_id": assistant_id,
                    }
            tool_record = {
                "id": tool_id,
                "stepIndex": event.step_index,
                "name": event.tool_call.name,
                "arguments": event.tool_call.arguments,
                "output": output,
                "success": tool_success,
                "errorMessage": event.tool_result.error_message,
                "state": tool_state,
                "approval": approval,
            }
            session.history_tools = upsert_tool(session.history_tools, tool_record)
            update_assistant_tool_call(
                session,
                assistant_id,
                tool_id,
                lambda existing: {
                    **existing,
                    **tool_record,
                },
            )
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
                        "success": tool_success,
                        "error_message": event.tool_result.error_message,
                        "terminal_output": terminal_output,
                        "preview_url": preview_url,
                        "state": tool_state,
                        "approval": approval,
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
        if resume_existing_turn:
            response = await asyncio.to_thread(
                session.chat_session.continue_turn,
                on_event,
            )
        else:
            if user_message is None:
                raise RuntimeError("续跑前缺少用户消息。")
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

        persisted_failure_content = (
            f"{streamed_assistant_text}{failure_message}"
            if streamed_assistant_text
            else failure_message.strip()
        )
        replace_assistant_text_part(session, assistant_id, persisted_failure_content.strip())
        set_session_generating(session, False)
        await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
        await queue.put(None)
        return

    if session.cancel_event.is_set():
        set_session_generating(session, False)
        await queue.put(None)
        return

    replace_assistant_text_part(session, assistant_id, response.final_output)
    remaining_output = response.final_output
    should_reset_before_replay = not assistant_stream_started
    if assistant_stream_started:
        if response.final_output.startswith(streamed_assistant_text):
            remaining_output = response.final_output[len(streamed_assistant_text) :]
        else:
            should_reset_before_replay = True
            remaining_output = response.final_output

    if should_reset_before_replay:
        clear_assistant_text_part(session, assistant_id)
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
    set_session_generating(session, False)


async def run_demo_stream(
    session: UISession,
    user_message: str,
    queue: asyncio.Queue[dict[str, Any] | None],
) -> None:
    assistant_id = uuid.uuid4().hex
    set_session_generating(session, True)
    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )
    update_assistant_history_message(session, assistant_id, lambda message: sync_assistant_message_fields(message))
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
                "output": read_text_file(demo_file, session.workspace) if demo_file else "当前工作区里暂时没有合适的文本文件可预览。",
                "success": bool(demo_file),
                "error_message": None if demo_file else "未找到可预览文件",
            },
        ),
    ]

    for event_type, payload in demo_events:
        if event_type == "thought":
            thought_text = str(payload["thought"])
            session.thoughts.append(thought_text)
            upsert_assistant_thinking_part(session, assistant_id, thought_text)
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        elif event_type == "tool_call":
            update_plan_steps_for_tool(
                session,
                payload.get("step_index"),
                str(payload.get("name", "")),
            )
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "state": "running",
                },
            )
            session.touch()
            payload = {**payload, "assistant_id": assistant_id}
        else:
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
            append_assistant_tool_call(
                session,
                assistant_id,
                {
                    "id": payload["id"],
                    "stepIndex": payload["step_index"],
                    "name": payload["name"],
                    "arguments": payload["arguments"],
                    "output": payload.get("output"),
                    "success": payload.get("success"),
                    "errorMessage": payload.get("error_message"),
                    "state": "completed" if payload.get("success", True) else "error",
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
    replace_assistant_text_part(session, assistant_id, answer)
    await queue.put({"type": "assistant_reset", "payload": {"id": assistant_id}})
    for chunk in chunk_text(answer):
        await queue.put({"type": "assistant_delta", "payload": {"id": assistant_id, "delta": chunk}})
        await asyncio.sleep(0.03)

    finalize_plan_steps(session)
    await queue.put({"type": "plan_steps", "payload": {"steps": session.plan_steps}})
    await queue.put({"type": "assistant_done", "payload": {"id": assistant_id}})
    await queue.put(None)
    set_session_generating(session, False)


def upsert_tool(current: list[dict[str, Any]], next_tool: dict[str, Any]) -> list[dict[str, Any]]:
    for index, tool in enumerate(current):
        if tool["id"] == next_tool["id"]:
            updated = current[:]
            updated[index] = {**tool, **next_tool}
            return updated
    return [*current, next_tool]


def upsert_message(current: list[dict[str, Any]], next_message: dict[str, Any]) -> list[dict[str, Any]]:
    for index, message in enumerate(current):
        if message.get("id") == next_message.get("id"):
            updated = current[:]
            updated[index] = {**message, **next_message}
            return updated
    return [*current, next_message]


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
    elif tool_name in {"execute", "excecute", "terminal_input", "terminal_wait"}:
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


def resolve_preview_path(raw_path: str, workspace: str) -> Path:
    workspace_root = resolve_workspace_path(workspace)
    normalized = raw_path.strip().strip("/")
    candidate = workspace_root if not normalized else (workspace_root / normalized).resolve()
    if workspace_root != candidate and workspace_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="预览路径越界")

    if candidate.is_dir():
        for entry_name in ("index.html", "index.htm"):
            entry = candidate / entry_name
            if entry.exists() and entry.is_file():
                return entry
        raise HTTPException(status_code=404, detail="目录下未找到 index.html")

    if not candidate.exists():
        raise HTTPException(status_code=404, detail="预览目标不存在")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="预览目标不是文件")
    return candidate


def build_file_tree(root: Path, max_depth: int = FILE_TREE_MAX_DEPTH) -> list[dict[str, Any]]:
    if not root.exists():
        return []

    def walk(target: Path, prefix: Path, depth: int) -> list[dict[str, Any]]:
        if depth > max_depth:
            return []
        items: list[dict[str, Any]] = []
        count = 0
        for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if count >= FILE_TREE_MAX_ENTRIES_PER_DIR:
                items.append({"path": str(target.resolve()), "name": "... (too many entries)", "type": "file"})
                break
            absolute = str(child.resolve())
            if child.is_dir():
                if child.name in FILE_TREE_IGNORED_DIR_NAMES:
                    continue
                items.append(
                    {
                        "path": absolute,
                        "name": child.name,
                        "type": "folder",
                        "children": walk(child, prefix, depth + 1),
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
            count += 1
        return items

    return [
        {
            "path": str(root.resolve()),
            "name": root.name,
            "type": "folder",
            "children": walk(root, root, 1),
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
        for match in _shallow_glob(workspace_root, name, max_depth=2):
            return str(match.resolve())

    for match in _shallow_glob_all(workspace_root, max_depth=2):
        if match.is_file() and match.suffix in {".py", ".ts", ".tsx", ".md", ".json"}:
            return str(match.resolve())
    return None


def _shallow_glob(root: Path, name: str, max_depth: int) -> list[Path]:
    results: list[Path] = []
    _walk_shallow(root, max_depth, lambda p: results.append(p) if p.name == name else None)
    return results[:5]


def _shallow_glob_all(root: Path, max_depth: int) -> list[Path]:
    results: list[Path] = []
    _walk_shallow(root, max_depth, lambda p: results.append(p))
    return results[:50]


def _walk_shallow(root: Path, max_depth: int, visitor: Any) -> None:
    if max_depth <= 0:
        return
    try:
        for child in root.iterdir():
            if child.name in FILE_TREE_IGNORED_DIR_NAMES:
                continue
            visitor(child)
            if child.is_dir():
                _walk_shallow(child, max_depth - 1, visitor)
    except PermissionError:
        pass


def pick_demo_file(workspace: str) -> str | None:
    return pick_default_file(workspace)


def render_demo_list_output(workspace: str) -> str:
    workspace_root = resolve_workspace_path(workspace)
    rendered = [f"# Path: {workspace_root}"]
    for child in sorted(workspace_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if child.is_dir() and child.name in FILE_TREE_IGNORED_DIR_NAMES:
            continue
        rendered.append(f"{child.name}/" if child.is_dir() else child.name)
    return "\n".join(rendered[:25])


def chunk_text(text: str, chunk_size: int = 28) -> list[str]:
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)] or [""]


def extract_terminal_output(output: object) -> str | None:
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        full_output = output.get("full_output")
        if isinstance(full_output, str):
            return full_output
    return None


def extract_preview_url(output: object) -> str | None:
    if isinstance(output, dict):
        resolved_url = output.get("resolved_url")
        if isinstance(resolved_url, str) and resolved_url.strip():
            return resolved_url
    return None


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


def scan_env_models() -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_models: set[str] = set()

    for env_path in sorted(ROOT.glob(".env*")):
        name = env_path.name
        if not env_path.is_file():
            continue
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            continue

        model_match = re.search(r"^SC_AGENT_MODEL\s*=\s*(.+)$", text, re.MULTILINE)
        base_url_match = re.search(r"^SC_AGENT_BASE_URL\s*=\s*(.+)$", text, re.MULTILINE)
        if not model_match:
            continue

        model_value = model_match.group(1).strip().strip("'\"")
        base_url_value = base_url_match.group(1).strip().strip("'\"") if base_url_match else ""

        if not model_value or model_value in seen_models:
            continue
        seen_models.add(model_value)

        provider = infer_provider_from_url(base_url_value)
        label = f"{model_value}" if name == ".env" else f"{model_value} ({name})"
        results.append({
            "id": model_value,
            "name": model_value,
            "provider": provider,
            "envFile": name,
            "label": label,
        })

    return results


def infer_provider_from_url(base_url: str) -> str:
    url_lower = base_url.lower()
    if "anthropic" in url_lower:
        return "anthropic"
    if "openai" in url_lower:
        return "openai"
    if "deepseek" in url_lower:
        return "deepseek"
    if "dashscope" in url_lower or "aliyun" in url_lower or "qwen" in url_lower:
        return "alibaba-cn"
    if "google" in url_lower or "gemini" in url_lower:
        return "google"
    if "groq" in url_lower:
        return "groq"
    if "mistral" in url_lower:
        return "mistral"
    if "xai" in url_lower:
        return "xai"
    if "openrouter" in url_lower:
        return "openrouter"
    if "together" in url_lower:
        return "togetherai"
    if "fireworks" in url_lower:
        return "fireworks-ai"
    if "cerebras" in url_lower:
        return "cerebras"
    return "openrouter"


if __name__ == "__main__":
    import uvicorn

    def _force_shutdown(signum: int, frame: Any) -> None:
        for session in _sessions.values():
            stop_session_execution(session)
            if session.terminal_runtime is not None:
                session.terminal_runtime.close()
            if session.interactive_command_session is not None:
                session.interactive_command_session.close()
        import os
        os._exit(0)

    signal.signal(signal.SIGINT, _force_shutdown)
    signal.signal(signal.SIGTERM, _force_shutdown)

    uvicorn.run(app, host="0.0.0.0", port=8000)
