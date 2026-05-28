from __future__ import annotations

from contextlib import asynccontextmanager, suppress

import signal

import asyncio
from copy import deepcopy
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse

try:
    from winpty import PtyProcess
except ImportError:  # pragma: no cover - optional dependency
    PtyProcess = None

from deploy_agent import DeployConnectionManager, DeployPromptModel, build_deploy_tools
from agent import Agent, AgentEvent, ChatSession, OpenAICompatibleClient
from coding_agent import CodingPromptModel, InteractiveCommandSession, build_coding_tools
from coding_agent.tools import (
    DEFAULT_IGNORED_DIR_NAMES,
    delete_file_in_workspace,
    execute_git_commit,
    execute_git_tag,
    init_git_repo,
)
from plan_agent import PlanPromptModel, build_plan_tools
from fastapi_app.agent_router import (
    decide_agent_route_with_model,
    normalize_route_state,
)
from fastapi_app.api_models import (
    ChatStreamRequest,
    ConnectToolSubmitRequest,
    ContinueChatStreamRequest,
    CreateTaskRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    FinishTaskRequest,
    GitCommitRequest,
    GitTagRequest,
    KanbanBoardCreateRequest,
    KanbanCardCreateRequest,
    KanbanCardReorderRequest,
    KanbanCardUpdateRequest,
    ModelConfigPayload,
    PlanSubmitRequest,
    PlanDraftUpdateRequest,
    SessionContextMessage,
    SessionContextCompressionRequest,
    SessionContextCompressionResponse,
    SessionContextResponse,
    SessionTokenUsage,
    SessionContextTool,
    SessionHistoryItem,
    SessionRestoreRequest,
    SwitchModelRequest,
    TerminalControlRequest,
    ModelConfigPayload,
    SettingsPayload,
    TerminalInputRequest,
    TerminalSnapshotResponse,
    ToolConfirmationRequest,
    ToolInputSubmitRequest,
    UIModelProviderPayload,
)
from fastapi_app.kanban_store import KanbanStore
from fastapi_app.plugin_registry import list_builtin_plugins
from fastapi_app.settings_store import (
    load_settings,
    save_settings,
)
from fastapi_app.skills import (
    list_available_skill_summaries,
    resolve_message_skills,
)
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
from fastapi_app.session_history import (
    append_assistant_part_delta,
    append_assistant_tool_call,
    chunk_text,
    clear_assistant_text_part,
    ensure_user_message_recorded,
    extract_message_thought_text,
    extract_preview_url,
    extract_terminal_output,
    finalize_plan_steps,
    record_confirmation_result_for_agent,
    record_tool_result_for_agent,
    replace_assistant_text_part,
    seed_chat_session_history,
    sync_assistant_message_fields,
    update_assistant_history_message,
    update_assistant_tool_call,
    update_plan_steps_for_tool,
    upsert_assistant_thinking_part,
    upsert_message,
    upsert_tool,
)
from fastapi_app.session_persistence import (
    persisted_state_to_history_item as persisted_state_to_history_item_impl,
    persist_session_state as persist_session_state_impl,
    session_has_persistable_history as session_has_persistable_history_impl,
    session_to_persisted_state,
    set_session_generating as set_session_generating_impl,
)
from fastapi_app.session_store import PersistedSessionState, SQLiteSessionStateAdapter
from fastapi_app.terminal_runtime import TerminalRuntimeBase
from fastapi_app.ui_message_stream import UIMessageStreamAdapter, sse_data
from fastapi_app.workspace_utils import (
    build_default_open_files,
    build_file_tree,
    list_child_directories,
    list_workspace_options as list_workspace_options_impl,
    normalize_relative_path,
    normalize_workspace as normalize_workspace_impl,
    pick_default_file,
    pick_demo_file,
    read_text_file,
    render_demo_list_output,
    resolve_preview_path,
    resolve_workspace_path,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT
BACKEND_BASE_URL = "http://localhost:3001"
DEFAULT_BROWSER_PREVIEW_URL = "http://localhost:8888"
DEFAULT_SELECTED_FILE = None
DEFAULT_OPEN_FILES = [
    "ChatLayout.tsx",
    "MessageList.tsx",
    "TerminalPanel.tsx",
    "ToolPanel.tsx",
    "FilePreview.tsx",
]
MAX_CODE_CHANGE_RECORDS = 300
MAX_CODE_CHANGE_DIFF_LINES = 80
CONTEXT_COMPRESSION_SUMMARY_PREFIX = "[会话压缩摘要]"
DEFAULT_CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.8
DEFAULT_CONTEXT_COMPRESSION_RECENT_MESSAGES = 6
DEFAULT_CONTEXT_COMPRESSION_RECENT_TOOLS = 8
DEFAULT_CONTEXT_COMPRESSION_RECENT_THOUGHTS = 4
MAX_CONTEXT_COMPRESSION_SOURCE_MESSAGES = 24
MAX_CONTEXT_COMPRESSION_SOURCE_TOOLS = 20
MAX_CONTEXT_COMPRESSION_SOURCE_THOUGHTS = 10
MAX_CONTEXT_COMPRESSION_SOURCE_CODE_CHANGES = 8

PREVIEW_SELECT_BRIDGE_SCRIPT = r"""
(() => {
  const READY = "SC_SELECT_BRIDGE_READY";
  const PING = "SC_SELECT_BRIDGE_PING";
  const START = "SC_SELECT_START";
  const CANCEL = "SC_SELECT_CANCEL";
  const RESULT = "SC_SELECT_RESULT";
  const ERROR = "SC_SELECT_ERROR";
  const HOVER_CLASS = "__sc-select-hover";
  const SELECTED_CLASS = "__sc-select-selected";
  const STYLE_ID = "__sc-select-bridge-style";

  if (window.__SUPER_CODE_SELECT_BRIDGE__) {
    window.parent?.postMessage({ type: READY, sourceUrl: window.location.href }, "*");
    return;
  }

  window.__SUPER_CODE_SELECT_BRIDGE__ = true;

  let selecting = false;
  let activeTarget = null;

  const post = (message) => {
    try {
      window.parent?.postMessage({ ...message, sourceUrl: window.location.href }, "*");
    } catch (error) {
      console.warn("[SuperCode] select bridge postMessage failed", error);
    }
  };

  const ensureStyle = () => {
    let style = document.getElementById(STYLE_ID);
    if (style) return style;
    style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      * { cursor: crosshair !important; }
      .${HOVER_CLASS} {
        outline: 2px dashed #3b82f6 !important;
        outline-offset: 2px !important;
        background-color: rgba(59, 130, 246, 0.1) !important;
      }
      .${SELECTED_CLASS} {
        outline: 2px solid #3b82f6 !important;
        outline-offset: 2px !important;
        background-color: rgba(59, 130, 246, 0.15) !important;
      }
    `;
    document.head.appendChild(style);
    return style;
  };

  const clearClasses = () => {
    document.querySelectorAll(`.${HOVER_CLASS}, .${SELECTED_CLASS}`).forEach((el) => {
      el.classList.remove(HOVER_CLASS, SELECTED_CLASS);
    });
    activeTarget = null;
  };

  const cleanup = () => {
    selecting = false;
    clearClasses();
    document.getElementById(STYLE_ID)?.remove();
    document.removeEventListener("mouseover", handleMouseOver, true);
    document.removeEventListener("mouseout", handleMouseOut, true);
    document.removeEventListener("click", handleClick, true);
    document.removeEventListener("keydown", handleKeyDown, true);
  };

  const getElementSelector = (el) => {
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let selector = current.tagName.toLowerCase();
      if (current.id) {
        selector += `#${CSS.escape(current.id)}`;
        parts.unshift(selector);
        break;
      }

      const classes = Array.from(current.classList || [])
        .filter((className) => className && !className.startsWith("__sc-select"));
      if (classes.length) {
        selector += classes.map((className) => `.${CSS.escape(className)}`).join("");
      }

      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(
          (sibling) => sibling.tagName === current.tagName,
        );
        if (siblings.length > 1) {
          selector += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        }
      }

      parts.unshift(selector);
      current = current.parentElement;
    }
    return parts.slice(-4).join(" > ");
  };

  function shouldIgnoreTarget(target) {
    return (
      !target ||
      !(target instanceof HTMLElement) ||
      target === document.body ||
      target === document.documentElement
    );
  }

  function handleMouseOver(event) {
    if (!selecting) return;
    event.stopPropagation();
    const target = event.target;
    if (shouldIgnoreTarget(target)) return;
    if (activeTarget && activeTarget !== target) {
      activeTarget.classList.remove(HOVER_CLASS);
    }
    activeTarget = target;
    target.classList.add(HOVER_CLASS);
  }

  function handleMouseOut(event) {
    if (!selecting) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
      target.classList.remove(HOVER_CLASS);
    }
  }

  function handleClick(event) {
    if (!selecting) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.target;
    if (shouldIgnoreTarget(target)) return;

    try {
      clearClasses();
      target.classList.add(SELECTED_CLASS);
      const selector = getElementSelector(target);
      const html = target.outerHTML;
      cleanup();
      post({ type: RESULT, selector, html });
    } catch (error) {
      cleanup();
      post({
        type: ERROR,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Escape") {
      cleanup();
      post({ type: CANCEL });
    }
  }

  const start = () => {
    if (selecting) return;
    selecting = true;
    ensureStyle();
    document.addEventListener("mouseover", handleMouseOver, true);
    document.addEventListener("mouseout", handleMouseOut, true);
    document.addEventListener("click", handleClick, true);
    document.addEventListener("keydown", handleKeyDown, true);
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const type = event.data?.type;
    if (type === START) {
      start();
      return;
    }
    if (type === PING) {
      post({ type: READY });
      return;
    }
    if (type === CANCEL) {
      cleanup();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => post({ type: READY }), { once: true });
  } else {
    post({ type: READY });
  }
})();
"""


def _empty_session_token_usage() -> dict[str, int]:
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "reasoningTokens": 0,
        "cachedInputTokens": 0,
        "totalTokens": 0,
    }


def normalize_session_token_usage(raw_usage: object) -> dict[str, int]:
    usage = _empty_session_token_usage()
    if not isinstance(raw_usage, dict):
        return usage

    for key in usage:
        value = raw_usage.get(key)
        if isinstance(value, bool):
            usage[key] = int(value)
        elif isinstance(value, (int, float)):
            usage[key] = max(int(value), 0)
    if usage["totalTokens"] == 0:
        usage["totalTokens"] = usage["inputTokens"] + usage["outputTokens"]
    return usage


def _resolve_state_db_path() -> Path:
    explicit = os.environ.get("SUPERCODE_STATE_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if "pytest" in sys.modules:
        return Path(tempfile.gettempdir()) / f"supercode-state-pytest-{os.getpid()}.sqlite3"
    return ROOT / ".supercode" / "state.sqlite3"


STATE_DB_PATH = _resolve_state_db_path()
_session_store = SQLiteSessionStateAdapter(STATE_DB_PATH)
_kanban_store = KanbanStore(STATE_DB_PATH)

class TerminalRuntime(TerminalRuntimeBase):
    def _get_pty_process_class(self) -> Any | None:
        return PtyProcess


@dataclass
class UISession:
    session_id: str
    model: str
    workspace: str
    reasoning_effort: str | None = None
    mode: str = "demo"
    agent_type: str = "coding"
    phase: str = "idle"
    route_state: dict[str, Any] = field(default_factory=dict)
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
    pending_user_input_requests: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    pending_connect_requests: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    deploy_connection_manager: DeployConnectionManager | None = field(default=None, repr=False)
    deploy_state: dict[str, Any] = field(default_factory=dict)
    plan_state: dict[str, Any] = field(default_factory=dict)
    history_messages: list[dict[str, Any]] = field(default_factory=list)
    history_tools: list[dict[str, Any]] = field(default_factory=list)
    code_changes: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[str] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    cumulative_token_usage: dict[str, int] = field(default_factory=dict)
    max_context_tokens: int | None = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    plan_steps: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.deploy_connection_manager is None:
            self.deploy_connection_manager = DeployConnectionManager(
                workspace=resolve_workspace_path(self.workspace)
            )
        self.phase = normalize_session_phase(self.phase)
        self.route_state = normalize_route_state(self.route_state)
        self.deploy_state = normalize_deploy_state(self.deploy_state)
        self.plan_state = normalize_plan_state(self.plan_state)
        self.token_usage = normalize_session_token_usage(self.token_usage)
        self.cumulative_token_usage = normalize_session_token_usage(self.cumulative_token_usage)
        self.max_context_tokens = self.max_context_tokens or infer_model_context_limit(self.model)
        refresh_session_runtime_state(self)

    def snapshot(self) -> CreateSessionResponse:
        if self.terminal_runtime is not None:
            self.terminal_output = self.terminal_runtime.snapshot(self.session_id).output
        refresh_session_runtime_state(self)
        return CreateSessionResponse(
            sessionId=self.session_id,
            model=self.model,
            modelId=resolve_model_reference_id(self.model, self.env_file),
            reasoningEffort=self.reasoning_effort,
            mode=self.mode,
            agentType=self.agent_type,
            phase=self.phase,
            routeState=self.route_state,
            deployState=self.deploy_state,
            planState=self.plan_state,
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
            availableSkills=list_available_skill_summaries(self.workspace),
            codeChanges=self.code_changes,
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
        include_output: bool = False,
        include_file_tree: bool = False,
        include_processes: bool = False,
    ) -> TerminalSnapshotResponse:
        if self.terminal_runtime is None:
            raise RuntimeError("terminal 不存在")
        snapshot = self.terminal_runtime.snapshot(
            self.session_id,
            include_output=include_output,
        )
        if include_output:
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
            supportsResize=snapshot.supportsResize,
            fileTree=self.get_file_tree() if include_file_tree else None,
            processes=self.get_managed_processes(active_only=True) if include_processes else None,
        )

    def history_snapshot(self) -> SessionHistoryItem:
        return SessionHistoryItem(
            sessionId=self.session_id,
            workspace=self.workspace,
            mode=self.mode,
            model=self.model,
            agentType=self.agent_type,
            title=self.summary_title(),
            preview=self.summary_preview(),
            messageCount=len(self.history_messages),
            toolCallCount=len(self.history_tools),
            createdAt=self.created_at,
            updatedAt=self.updated_at,
        )

    def context_snapshot(self) -> SessionContextResponse:
        refresh_session_runtime_state(self)
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
            reasoningEffort=self.reasoning_effort,
            agentType=self.agent_type,
            phase=self.phase,
            routeState=self.route_state,
            deployState=self.deploy_state,
            planState=self.plan_state,
            selectedFilePath=self.selected_file_path,
            openFiles=self.open_files[-6:],
            messageCount=len(self.history_messages),
            toolCallCount=len(self.history_tools),
            thoughtCount=len(self.thoughts),
            estimatedTokens=estimate_session_context_tokens(self),
            maxTokens=max(self.max_context_tokens or infer_model_context_limit(self.model), 1),
            usage=SessionTokenUsage(**normalize_session_token_usage(self.token_usage)),
            cumulativeUsage=SessionTokenUsage(**normalize_session_token_usage(self.cumulative_token_usage)),
            recentMessages=recent_messages,
            recentThoughts=self.thoughts[-6:],
            recentTools=recent_tools,
            codeChangeCount=len(self.code_changes),
            recentCodeChanges=self.code_changes[-8:],
            availableSkills=list_available_skill_summaries(self.workspace),
            planSteps=self.plan_steps,
        )

    def touch(self) -> None:
        self.updated_at = int(time.time() * 1000)
        refresh_session_runtime_state(self)
        sync_session_runtime_state_for_agent(self)
        persist_session_state(self)

    def summary_title(self) -> str:
        for message in self.history_messages:
            if str(message.get("role")) == "user":
                content = compact_text(str(message.get("content", "")), 40)
                if content:
                    return content
        plan_state = normalize_plan_state(self.plan_state)
        plan = (
            plan_state.get("last_submitted_plan")
            if isinstance(plan_state.get("last_submitted_plan"), dict)
            else plan_state.get("draft")
            if isinstance(plan_state.get("draft"), dict)
            else None
        )
        if isinstance(plan, dict):
            title = compact_text(str(plan.get("title") or ""), 40)
            if title:
                return f"计划：{title}"
        workspace_name = Path(self.workspace).name or self.workspace
        return f"{workspace_name} 新对话"

    def summary_preview(self) -> str:
        for message in reversed(self.history_messages):
            content = compact_text(str(message.get("content", "")), 72)
            if content:
                return content
        plan_state = normalize_plan_state(self.plan_state)
        plan = (
            plan_state.get("last_submitted_plan")
            if isinstance(plan_state.get("last_submitted_plan"), dict)
            else plan_state.get("draft")
            if isinstance(plan_state.get("draft"), dict)
            else None
        )
        if isinstance(plan, dict):
            summary = compact_text(str(plan.get("summary") or ""), 72)
            if summary:
                return summary
        return "还没有消息内容"


@dataclass(slots=True)
class ContextCompressionSlices:
    archived_messages: list[dict[str, Any]]
    preserved_messages: list[dict[str, Any]]
    archived_tools: list[dict[str, Any]]
    preserved_tools: list[dict[str, Any]]
    archived_thoughts: list[str]
    preserved_thoughts: list[str]


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


app = FastAPI(
    title="SuperCode Agent UI API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TERMINAL_WS_INITIAL_REPLAY_MAX_CHARS = 64_000
TERMINAL_WS_OUTPUT_CHUNK_CHARS = 8_192


@app.get("/scalar", include_in_schema=False)
def scalar_docs():
    return HTMLResponse("""
<!doctype html>
<html>
  <head>
    <title>SuperCode API Docs</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi.json"
      src="https://cdn.jsdelivr.net/npm/@scalar/api-reference">
    </script>
  </body>
</html>
""")

_sessions: dict[str, UISession] = {}

ROUTER_GENERIC_FOLLOWUPS = {
    "continue",
    "go on",
    "next",
    "继续",
    "继续吧",
    "然后呢",
    "然后",
    "再继续",
    "接着来",
    "再来",
    "看下",
    "看看",
    "再看看",
}

DEPLOY_ROUTE_KEYWORDS = (
    "deploy",
    "deployment",
    "release",
    "upload",
    "transfer",
    "vercel",
    "netlify",
    "docker",
    "compose",
    "staging",
    "production",
    "rollback",
    "上线",
    "部署",
    "发布",
    "上传",
    "传输",
    "同步文件",
    "传文件",
    "回滚",
    "预发",
    "生产环境",
    "预览环境",
    "服务器",
    "日志",
    "环境变量",
)

CODING_ROUTE_KEYWORDS = (
    "implement",
    "refactor",
    "fix",
    "bug",
    "test",
    "frontend",
    "backend",
    "component",
    "api",
    "function",
    "class",
    "write code",
    "修改代码",
    "写代码",
    "实现",
    "重构",
    "修复",
    "测试",
    "前端",
    "后端",
    "组件",
    "接口",
    "函数",
    "类",
    "页面",
    "样式",
    "脚本",
)

PLAN_ROUTE_KEYWORDS = (
    "plan",
    "planning",
    "research",
    "clarify",
    "scope",
    "需求澄清",
    "先别写代码",
    "先规划",
    "先计划",
    "先调研",
    "先梳理",
    "出个计划",
    "列个计划",
    "做方案",
    "需求分析",
    "技术方案",
)

PLAN_GENERIC_FOLLOWUPS = ROUTER_GENERIC_FOLLOWUPS | {
    "改下计划",
    "调整计划",
    "修改计划",
    "继续改计划",
    "再细一点",
    "再具体一点",
}

VAGUE_REQUIREMENT_KEYWORDS = (
    "做一个",
    "做个",
    "搞一个",
    "整一个",
    "搭一个",
    "弄一个",
    "优化一下",
    "先看看",
    "想做",
    "想搞",
    "需要一个",
)

CODE_FILE_SUFFIXES = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".vue",
    ".svelte",
    ".css",
    ".scss",
    ".html",
    ".json",
    ".yml",
    ".yaml",
}

SUPPORTED_EDITOR_COMMANDS = {
    "code",
    "code-insiders",
    "zed",
    "devenv",
    "subl",
    "webstorm",
}


def normalize_session_phase(phase: str | None) -> str:
    normalized = str(phase or "idle").strip().lower()
    allowed = {
        "idle",
        "clarifying",
        "researching",
        "planning",
        "awaiting_user_input",
        "plan_ready",
        "submitted",
        "awaiting_connect_input",
        "connected",
        "exploring",
        "executing",
        "verifying",
        "completed",
        "failed",
    }
    return normalized if normalized in allowed else "idle"


ALLOWED_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
}


def normalize_reasoning_effort(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized == "default":
        return None
    if normalized not in ALLOWED_REASONING_EFFORTS:
        raise ValueError("reasoning_effort 仅支持 none、minimal、low、medium、high、xhigh 或 default。")
    return normalized


def build_default_deploy_state() -> dict[str, Any]:
    return {
        "active_session_id": None,
        "active_root_path": None,
        "active_display_name": None,
        "active_host": None,
        "active_username": None,
        "active_extra_info": None,
        "pending_tool_id": None,
        "pending_tool_name": None,
        "pending_input_kind": None,
        "last_tool_name": None,
        "last_tool_state": None,
        "last_command": None,
        "last_command_cwd": None,
        "last_exit_code": None,
        "last_error": None,
        "last_message": None,
        "connection_count": 0,
        "known_session_ids": [],
    }


def normalize_deploy_state(value: object) -> dict[str, Any]:
    state = build_default_deploy_state()
    if isinstance(value, dict):
        for key in state:
            if key in value:
                state[key] = value[key]
    return state


def build_default_plan_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "draft": None,
        "last_submitted_plan": None,
        "pending_coding_input": None,
        "tasks": [],
        "active_task_id": None,
        "active_step_id": None,
    }


def _normalize_step_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    return normalized if normalized in {"pending", "running", "completed"} else "pending"


def _normalize_task_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    return normalized if normalized in {"pending", "running", "completed"} else "pending"


def _normalize_plan_tasks(raw_tasks: object) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []

    tasks: list[dict[str, Any]] = []
    for task_index, raw_task in enumerate(raw_tasks, start=1):
        if not isinstance(raw_task, dict):
            continue
        task_id = str(raw_task.get("id") or "").strip()
        title = str(raw_task.get("title") or "").strip()
        summary = str(raw_task.get("summary") or "").strip()
        source = str(raw_task.get("source") or "").strip() or "coding"
        raw_steps = raw_task.get("steps")
        if not task_id or not title or not summary or not isinstance(raw_steps, list):
            continue

        steps: list[dict[str, Any]] = []
        for step_index, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            step_id = str(raw_step.get("id") or "").strip()
            step_title = str(raw_step.get("title") or "").strip()
            step_summary = str(raw_step.get("summary") or "").strip()
            if not step_id or not step_title or not step_summary:
                continue
            steps.append(
                {
                    "id": step_id,
                    "title": step_title,
                    "summary": step_summary,
                    "status": _normalize_step_status(raw_step.get("status")),
                    "order": int(raw_step.get("order") or step_index),
                }
            )

        if not steps:
            continue

        tasks.append(
            {
                "id": task_id,
                "title": title,
                "summary": summary,
                "status": _normalize_task_status(raw_task.get("status")),
                "source": source,
                "steps": steps,
                "order": int(raw_task.get("order") or task_index),
            }
        )

    return tasks


def _find_task_by_id(tasks: list[dict[str, Any]], task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    return next((task for task in tasks if str(task.get("id")) == task_id), None)


def _find_active_task(tasks: list[dict[str, Any]], active_task_id: str | None) -> dict[str, Any] | None:
    active_task = _find_task_by_id(tasks, active_task_id)
    if active_task is not None:
        return active_task
    return next((task for task in tasks if str(task.get("status")) == "running"), None)


def _derive_plan_steps_from_tasks(plan_state: dict[str, Any]) -> list[dict[str, str]]:
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    display_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if display_task is None and tasks:
        display_task = tasks[-1]
    if display_task is None:
        return []

    steps = display_task.get("steps")
    if not isinstance(steps, list):
        return []

    return [
        {
            "id": str(step.get("id") or ""),
            "title": str(step.get("title") or ""),
            "description": str(step.get("summary") or ""),
            "status": _normalize_step_status(step.get("status")),
        }
        for step in steps
        if isinstance(step, dict)
    ]


def _sync_plan_steps_from_tasks(session: UISession) -> None:
    derived_steps = _derive_plan_steps_from_tasks(session.plan_state)
    if derived_steps:
        session.plan_steps = derived_steps


def ensure_deploy_plan_steps(session: UISession) -> None:
    if session.agent_type != "deploy" or session.plan_steps:
        return
    session.plan_steps = [
        {
            "id": "deploy-connect",
            "title": "连接部署目标",
            "description": "选择或填写部署目标信息，准备建立部署连接。",
            "status": "running",
        },
        {
            "id": "deploy-explore",
            "title": "探索部署目录",
            "description": "读取部署目录、配置文件和发布脚本，确认发布方式。",
            "status": "pending",
        },
        {
            "id": "deploy-execute",
            "title": "执行部署命令",
            "description": "同步文件或执行部署命令，并收集部署结果。",
            "status": "pending",
        },
    ]


def _build_task_payload(
    *,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
    source: str,
    order: int,
) -> dict[str, Any]:
    task_id = f"task_{uuid.uuid4().hex[:10]}"
    normalized_steps = [
        {
            "id": f"step_{uuid.uuid4().hex[:10]}",
            "title": str(step.get("title") or "").strip(),
            "summary": str(step.get("summary") or "").strip(),
            "status": "running" if index == 0 else "pending",
            "order": index + 1,
        }
        for index, step in enumerate(steps)
    ]
    return {
        "id": task_id,
        "title": title,
        "summary": summary,
        "status": "running",
        "source": source,
        "steps": normalized_steps,
        "order": order,
    }


def create_task_in_session(
    session: UISession,
    *,
    title: str,
    summary: str,
    steps: list[dict[str, str]],
    source: str,
) -> dict[str, Any]:
    normalized_title = str(title or "").strip()
    normalized_summary = str(summary or "").strip()
    normalized_steps = [
        {
            "title": str(step.get("title") or "").strip(),
            "summary": str(step.get("summary") or "").strip(),
        }
        for step in steps
        if str(step.get("title") or "").strip() and str(step.get("summary") or "").strip()
    ]
    if not normalized_title:
        raise HTTPException(status_code=400, detail="title 不能为空。")
    if not normalized_summary:
        raise HTTPException(status_code=400, detail="summary 不能为空。")
    if not normalized_steps:
        raise HTTPException(status_code=400, detail="steps 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    previous_active_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if previous_active_task is not None:
        previous_active_task["status"] = "pending"
        for step in previous_active_task.get("steps", []):
            if isinstance(step, dict) and str(step.get("status")) == "running":
                step["status"] = "pending"

    task = _build_task_payload(
        title=normalized_title,
        summary=normalized_summary,
        steps=normalized_steps,
        source=source,
        order=len(tasks) + 1,
    )
    tasks.append(task)
    task_steps = task.get("steps")
    if not task_steps:
        raise HTTPException(status_code=400, detail="创建的 task 至少需要一个 step。")
    first_step = task_steps[0]
    update_plan_state(
        session,
        tasks=tasks,
        active_task_id=task["id"],
        active_step_id=first_step["id"],
    )
    session.touch()
    return task


def finish_task_step_in_session(session: UISession, step_id: str) -> dict[str, Any]:
    normalized_step_id = str(step_id or "").strip()
    if not normalized_step_id:
        raise HTTPException(status_code=400, detail="step_id 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    active_step_id = str(plan_state.get("active_step_id") or "").strip()
    if active_step_id != normalized_step_id:
        raise HTTPException(status_code=409, detail="只能完成当前正在执行的 step。")

    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    active_task = _find_active_task(tasks, str(plan_state.get("active_task_id") or "").strip() or None)
    if active_task is None:
        raise HTTPException(status_code=404, detail="当前没有可完成的 task。")

    steps = active_task.get("steps")
    if not isinstance(steps, list):
        raise HTTPException(status_code=404, detail="当前 task 没有 steps。")

    current_index = next(
        (index for index, step in enumerate(steps) if str(step.get("id")) == normalized_step_id),
        None,
    )
    if current_index is None:
        raise HTTPException(status_code=404, detail="step_id 不存在。")

    current_step = steps[current_index]
    current_step["status"] = "completed"
    next_step_id: str | None = None
    next_index = current_index + 1
    if next_index < len(steps):
        next_step = steps[next_index]
        next_step["status"] = "running"
        active_task["status"] = "running"
        next_step_id = str(next_step.get("id") or "").strip() or None
    else:
        active_task["status"] = "completed"

    update_plan_state(
        session,
        tasks=tasks,
        active_task_id=(str(active_task.get("id") or "").strip() if next_step_id else None),
        active_step_id=next_step_id,
    )
    session.touch()
    return {
        "task_id": str(active_task.get("id") or ""),
        "step_id": normalized_step_id,
        "finished": True,
        "next_step_id": next_step_id,
    }


def build_task_status_payload(session: UISession, task_id: str | None = None) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    tasks = _normalize_plan_tasks(plan_state.get("tasks"))
    active_task_id = str(plan_state.get("active_task_id") or "").strip() or None
    active_step_id = str(plan_state.get("active_step_id") or "").strip() or None
    active_task = _find_task_by_id(tasks, task_id) if task_id else _find_active_task(tasks, active_task_id)
    if active_task is None and tasks:
        active_task = tasks[-1]
    return {
        "active_task_id": active_task_id,
        "active_step_id": active_step_id,
        "active_task": active_task,
        "tasks": tasks,
    }


def normalize_plan_state(value: object) -> dict[str, Any]:
    state = build_default_plan_state()
    if isinstance(value, dict):
        for key in state:
            if key in value:
                state[key] = value[key]
    if not isinstance(state.get("draft"), dict):
        state["draft"] = None
    if not isinstance(state.get("last_submitted_plan"), dict):
        state["last_submitted_plan"] = None
    pending_coding_input = state.get("pending_coding_input")
    state["pending_coding_input"] = (
        str(pending_coding_input).strip() if isinstance(pending_coding_input, str) else None
    )
    state["tasks"] = _normalize_plan_tasks(state.get("tasks"))
    active_task = _find_active_task(state["tasks"], str(state.get("active_task_id") or "").strip() or None)
    state["active_task_id"] = str(active_task.get("id") or "").strip() if active_task else None
    active_step_id = str(state.get("active_step_id") or "").strip() or None
    if active_task is None:
        state["active_step_id"] = None
    else:
        steps = active_task.get("steps")
        if isinstance(steps, list) and any(str(step.get("id")) == active_step_id for step in steps if isinstance(step, dict)):
            state["active_step_id"] = active_step_id
        else:
            running_step = next(
                (
                    step
                    for step in steps
                    if isinstance(step, dict) and str(step.get("status")) == "running"
                ),
                None,
            )
            state["active_step_id"] = str(running_step.get("id") or "").strip() if running_step else None
    status = str(state.get("status") or "idle").strip().lower()
    if status not in {"idle", "clarifying", "researching", "planning", "awaiting_user_input", "draft_ready", "submitted"}:
        state["status"] = "idle"
    else:
        state["status"] = status
    return state


def refresh_session_runtime_state(session: UISession) -> None:
    if session.agent_type == "plan":
        session.plan_state = normalize_plan_state(session.plan_state)
        _sync_plan_steps_from_tasks(session)
        session.deploy_state = normalize_deploy_state(session.deploy_state)
        if session.pending_user_input_requests:
            session.phase = "awaiting_user_input"
            session.plan_state["status"] = "awaiting_user_input"
            return
        if session.plan_state.get("status") in {"clarifying", "researching", "planning"}:
            session.phase = (
                "planning"
                if session.plan_state.get("status") == "planning"
                else str(session.plan_state.get("status"))
            )
            return
        if session.plan_state.get("draft"):
            session.phase = "plan_ready"
            if session.plan_state.get("status") != "submitted":
                session.plan_state["status"] = "draft_ready"
            return
        session.phase = normalize_session_phase(session.phase)
        if session.phase not in {"clarifying", "researching", "planning"}:
            session.phase = "clarifying"
        if session.plan_state.get("status") == "idle":
            session.plan_state["status"] = "clarifying"
        return

    if session.agent_type != "deploy":
        session.phase = "idle"
        session.plan_state = normalize_plan_state(session.plan_state)
        _sync_plan_steps_from_tasks(session)
        session.deploy_state = normalize_deploy_state(session.deploy_state)
        return

    session.phase = normalize_session_phase(session.phase)
    deploy_state = normalize_deploy_state(session.deploy_state)
    session.plan_state = normalize_plan_state(session.plan_state)
    _sync_plan_steps_from_tasks(session)
    ensure_deploy_plan_steps(session)
    manager = session.deploy_connection_manager
    connections = manager.list_connections() if manager is not None else []
    deploy_state["connection_count"] = len(connections)
    deploy_state["known_session_ids"] = [
        str(connection.get("session_id") or "")
        for connection in connections[:10]
        if str(connection.get("session_id") or "").strip()
    ]

    active_session_id = str(deploy_state.get("active_session_id") or "").strip()
    if active_session_id and manager is not None:
        try:
            active_connection = manager.get_connection(active_session_id)
        except KeyError:
            deploy_state["active_session_id"] = None
            deploy_state["active_root_path"] = None
            deploy_state["active_display_name"] = None
            deploy_state["active_host"] = None
            deploy_state["active_username"] = None
            deploy_state["active_extra_info"] = None
        else:
            if active_connection.host and not manager.has_password(active_session_id):
                deploy_state["active_session_id"] = None
                deploy_state["active_root_path"] = None
                deploy_state["active_display_name"] = None
                deploy_state["active_host"] = None
                deploy_state["active_username"] = None
                deploy_state["active_extra_info"] = None
            else:
                deploy_state["active_root_path"] = str(active_connection.root_path)
                deploy_state["active_display_name"] = active_connection.display_name
                deploy_state["active_host"] = active_connection.host or None
                deploy_state["active_username"] = active_connection.username or None
                deploy_state["active_extra_info"] = active_connection.extra_info or None

    pending_tool_id = str(deploy_state.get("pending_tool_id") or "").strip()
    pending_input_kind = str(deploy_state.get("pending_input_kind") or "").strip()
    if pending_tool_id and pending_input_kind and pending_tool_id not in session.pending_connect_requests:
        deploy_state["pending_tool_id"] = None
        deploy_state["pending_tool_name"] = None
        deploy_state["pending_input_kind"] = None

    session.deploy_state = deploy_state


def build_agent_runtime_state(session: UISession) -> dict[str, Any]:
    refresh_session_runtime_state(session)
    return {
        "agent_type": session.agent_type,
        "phase": session.phase,
        "workspace": session.workspace,
        "route_state": session.route_state,
        "deploy_state": session.deploy_state if session.agent_type == "deploy" else {},
        "plan_state": session.plan_state,
    }


def sync_session_runtime_state_for_agent(session: UISession) -> None:
    if session.chat_session is None:
        return
    state = getattr(session.chat_session, "state", None)
    data = getattr(state, "data", None)
    if not isinstance(data, dict):
        return
    data["runtime_state"] = build_agent_runtime_state(session)
    data["available_skills"] = list_available_skill_summaries(session.workspace)


def set_session_phase(session: UISession, phase: str) -> None:
    session.phase = normalize_session_phase(phase)


def update_deploy_state(session: UISession, **updates: Any) -> None:
    if session.agent_type != "deploy":
        return
    deploy_state = normalize_deploy_state(session.deploy_state)
    for key, value in updates.items():
        if key in deploy_state:
            deploy_state[key] = value
    session.deploy_state = deploy_state
    refresh_session_runtime_state(session)


def update_plan_state(session: UISession, **updates: Any) -> None:
    plan_state = normalize_plan_state(session.plan_state)
    for key, value in updates.items():
        if key in plan_state:
            plan_state[key] = value
    session.plan_state = normalize_plan_state(plan_state)
    refresh_session_runtime_state(session)


def reset_phase_for_new_turn(session: UISession) -> None:
    if session.agent_type == "plan":
        refresh_session_runtime_state(session)
        if session.pending_user_input_requests:
            set_session_phase(session, "awaiting_user_input")
            update_plan_state(session, status="awaiting_user_input")
            return
        if session.plan_state.get("draft"):
            set_session_phase(session, "plan_ready")
            update_plan_state(session, status="draft_ready")
            return
        set_session_phase(session, "clarifying")
        update_plan_state(session, status="clarifying")
        return
    if session.agent_type != "deploy":
        set_session_phase(session, "idle")
        return
    refresh_session_runtime_state(session)
    if session.pending_connect_requests:
        set_session_phase(session, "awaiting_connect_input")
        return
    if session.deploy_state.get("active_session_id"):
        set_session_phase(session, "connected")
        return
    set_session_phase(session, "idle")


def extract_command_exit_code(output: object) -> int | None:
    if not isinstance(output, str):
        return None
    for line in output.splitlines():
        normalized = line.strip().lower()
        if not normalized.startswith("exit_code:"):
            continue
        raw_value = line.split(":", 1)[1].strip()
        try:
            return int(raw_value)
        except ValueError:
            return None
    return None


def _normalized_message_for_routing(user_message: str) -> str:
    return " ".join(user_message.strip().lower().split())


def _contains_any_keyword(text: str, keywords: tuple[str, ...] | set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _message_has_specific_path_hint(text: str) -> bool:
    return bool(
        re.search(r"[\w./-]+\.(ts|tsx|js|jsx|py|go|rs|java|kt|swift|vue|svelte|json|yml|yaml|css|scss|html|md)\b", text)
        or "/" in text
        or "\\" in text
        or "第" in text and "行" in text
    )


def _workspace_looks_empty(workspace: str) -> bool:
    workspace_path = resolve_workspace_path(workspace)
    relevant_files = 0
    code_files = 0
    for current_root, dirnames, filenames in os.walk(workspace_path, topdown=True):
        dirnames[:] = [name for name in dirnames if name not in DEFAULT_IGNORED_DIR_NAMES]
        if Path(current_root).name == ".git":
            continue
        for filename in filenames:
            if filename.startswith(".") and filename not in {".env", ".gitignore"}:
                continue
            relevant_files += 1
            if Path(filename).suffix.lower() in CODE_FILE_SUFFIXES:
                code_files += 1
            if relevant_files > 10 and code_files > 0:
                return False
    return relevant_files <= 3 or code_files == 0


def _is_vague_requirement(text: str) -> bool:
    if _contains_any_keyword(text, VAGUE_REQUIREMENT_KEYWORDS):
        return True
    if _message_has_specific_path_hint(text):
        return False
    if _contains_any_keyword(text, DEPLOY_ROUTE_KEYWORDS):
        return False
    if any(keyword in text for keyword in ("api", "接口", "组件", "函数", "页面", "数据库", "表", "测试")):
        return False
    return len(text) <= 16


def _is_plan_session_active(session: UISession) -> bool:
    if session.agent_type != "plan":
        return False
    plan_state = normalize_plan_state(session.plan_state)
    return plan_state.get("status") != "submitted"


def _should_force_plan_route(session: UISession, text: str) -> bool:
    if _contains_any_keyword(text, PLAN_ROUTE_KEYWORDS):
        return True
    if _is_plan_session_active(session) and text in PLAN_GENERIC_FOLLOWUPS:
        return True
    if _contains_any_keyword(text, DEPLOY_ROUTE_KEYWORDS):
        return False
    if _message_has_specific_path_hint(text):
        return False
    if _workspace_looks_empty(session.workspace) and not session.history_messages:
        return True
    return _is_vague_requirement(text)


def route_agent_type_for_message(session: UISession, user_message: str) -> str:
    text = _normalized_message_for_routing(user_message)
    if not text:
        return session.agent_type

    if session.pending_connect_requests:
        return "deploy"
    if session.pending_user_input_requests:
        return "plan"
    pending_coding_input = str(normalize_plan_state(session.plan_state).get("pending_coding_input") or "").strip()
    if pending_coding_input and text == _normalized_message_for_routing(pending_coding_input):
        return "coding"

    active_deploy_session = bool(normalize_deploy_state(session.deploy_state).get("active_session_id"))

    if _contains_any_keyword(text, CODING_ROUTE_KEYWORDS):
        return "coding"

    if active_deploy_session and text in ROUTER_GENERIC_FOLLOWUPS:
        return "deploy"
    if active_deploy_session and session.agent_type == "deploy":
        return "deploy"

    if _should_force_plan_route(session, text):
        return "plan"

    if _contains_any_keyword(text, DEPLOY_ROUTE_KEYWORDS):
        return "deploy"

    if _is_plan_session_active(session):
        return "plan"

    return "coding"


def _fallback_route_decision(
    session: UISession,
    user_message: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    previous_agent_type = session.agent_type
    agent_type = route_agent_type_for_message(session, user_message)
    return normalize_route_state(
        {
            "agentType": agent_type,
            "confidence": 0.55,
            "reason": reason or "模型路由不可用，已使用规则兜底选择智能体。",
            "source": "fallback",
            "fallbackUsed": True,
            "keepCurrentAgent": agent_type == previous_agent_type,
            "previousAgentType": previous_agent_type,
        }
    )


def _forced_route_decision(session: UISession, agent_type: str) -> dict[str, Any]:
    return normalize_route_state(
        {
            "agentType": agent_type,
            "confidence": 1.0,
            "reason": "用户在模式选择器中指定了智能体模式。",
            "source": "forced",
            "fallbackUsed": False,
            "keepCurrentAgent": agent_type == session.agent_type,
            "previousAgentType": session.agent_type,
        }
    )


def _build_router_workspace_summary(session: UISession) -> dict[str, Any]:
    return {
        "looksEmpty": _workspace_looks_empty(session.workspace),
        "selectedFilePath": session.selected_file_path,
    }


def _build_router_plan_summary(session: UISession) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    draft = plan_state.get("draft") if isinstance(plan_state.get("draft"), dict) else None
    submitted = (
        plan_state.get("last_submitted_plan")
        if isinstance(plan_state.get("last_submitted_plan"), dict)
        else None
    )
    active_task = _find_active_task(
        _normalize_plan_tasks(plan_state.get("tasks")),
        str(plan_state.get("active_task_id") or "").strip() or None,
    )
    return {
        "status": plan_state.get("status"),
        "hasDraft": bool(draft),
        "hasSubmittedPlan": bool(submitted),
        "draftTitle": str((draft or {}).get("title") or "").strip() or None,
        "submittedTitle": str((submitted or {}).get("title") or "").strip() or None,
        "pendingCodingInput": bool(plan_state.get("pending_coding_input")),
        "activeTaskTitle": str((active_task or {}).get("title") or "").strip() or None,
        "activeStepId": plan_state.get("active_step_id"),
    }


def _build_router_deploy_summary(session: UISession) -> dict[str, Any]:
    deploy_state = normalize_deploy_state(session.deploy_state)
    return {
        "hasActiveSession": bool(deploy_state.get("active_session_id")),
        "activeDisplayName": deploy_state.get("active_display_name"),
        "activeHost": deploy_state.get("active_host"),
        "pendingInputKind": deploy_state.get("pending_input_kind"),
        "connectionCount": deploy_state.get("connection_count"),
    }


def _build_router_context(session: UISession) -> dict[str, Any]:
    recent_user_messages = [
        compact_text(str(message.get("content") or ""), 120)
        for message in session.history_messages
        if str(message.get("role") or "") == "user" and str(message.get("content") or "").strip()
    ]
    return {
        "currentAgentType": session.agent_type,
        "phase": session.phase,
        "pending": {
            "connectRequests": bool(session.pending_connect_requests),
            "planQuestions": bool(session.pending_user_input_requests),
        },
        "plan": _build_router_plan_summary(session),
        "deploy": _build_router_deploy_summary(session),
        "workspace": _build_router_workspace_summary(session),
        "recentUserMessages": recent_user_messages[-3:],
    }


def decide_route_for_message(session: UISession, user_message: str) -> dict[str, Any]:
    text = _normalized_message_for_routing(user_message)
    if not text:
        return normalize_route_state(
            {
                "agentType": session.agent_type,
                "confidence": 1.0,
                "reason": "空消息保持当前智能体。",
                "source": "fallback",
                "fallbackUsed": True,
                "keepCurrentAgent": True,
                "previousAgentType": session.agent_type,
            }
        )

    if session.pending_connect_requests:
        return _fallback_route_decision(session, user_message, reason="当前正在等待部署连接信息，保持部署智能体。")
    if session.pending_user_input_requests:
        return _fallback_route_decision(session, user_message, reason="当前正在等待计划问题回答，保持计划智能体。")
    pending_coding_input = str(normalize_plan_state(session.plan_state).get("pending_coding_input") or "").strip()
    if pending_coding_input and text == _normalized_message_for_routing(pending_coding_input):
        return normalize_route_state(
            {
                "agentType": "coding",
                "confidence": 1.0,
                "reason": "这是已提交计划生成的编码输入，直接进入编码智能体。",
                "source": "fallback",
                "fallbackUsed": False,
                "keepCurrentAgent": session.agent_type == "coding",
                "previousAgentType": session.agent_type,
            }
        )

    if session.mode != "agent":
        return _fallback_route_decision(session, user_message, reason="真实模型运行时不可用，已使用规则兜底选择智能体。")

    try:
        config, _model_ref = build_agent_config(ROOT, session.env_file)
        config.reasoning_effort = None
        return decide_agent_route_with_model(
            OpenAICompatibleClient(config),
            user_message=user_message,
            context=_build_router_context(session),
        )
    except Exception as exc:  # noqa: BLE001 - 路由失败必须降级，不能阻断聊天
        return _fallback_route_decision(
            session,
            user_message,
            reason=f"模型路由失败，已使用规则兜底。原因：{compact_text(str(exc), 160)}",
        )


def rebuild_chat_session_for_agent_type(session: UISession, agent_type: str) -> None:
    chat_session, model_name, startup_error, env_file_used, reasoning_effort = build_chat_session(
        session.workspace,
        session.env_file,
        agent_type=agent_type,
        reasoning_effort=session.reasoning_effort,
    )

    session.agent_type = agent_type
    session.chat_session = chat_session
    session.mode = "agent" if chat_session is not None else "demo"
    session.startup_error = startup_error
    session.env_file = env_file_used or session.env_file
    session.reasoning_effort = reasoning_effort
    if chat_session is not None:
        session.model = model_name
        session.max_context_tokens = infer_model_context_limit(session.model)
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        if isinstance(session.chat_session.agent, Agent):
            attach_agent_runtime_metadata(
                session.chat_session.agent,
                session_id=session.session_id,
                interactive_command_session=session.interactive_command_session,
                cancel_event=session.cancel_event,
                deploy_connection_manager=session.deploy_connection_manager,
            )
            sync_session_runtime_state_for_agent(session)


def route_session_for_user_message(
    session: UISession,
    user_message: str,
    forced_agent_type: str | None = None,
) -> None:
    route_state = (
        _forced_route_decision(session, forced_agent_type)
        if forced_agent_type
        else decide_route_for_message(session, user_message)
    )
    next_agent_type = str(route_state.get("agentType") or session.agent_type)
    session.route_state = normalize_route_state(route_state)
    if next_agent_type != session.agent_type or session.chat_session is None:
        rebuild_chat_session_for_agent_type(session, next_agent_type)
    else:
        session.agent_type = next_agent_type

    if session.agent_type == "plan":
        reset_phase_for_new_turn(session)
    elif session.agent_type != "deploy":
        session.plan_steps = []
        set_session_phase(session, "idle")
    else:
        reset_phase_for_new_turn(session)
    sync_session_runtime_state_for_agent(session)





def session_has_persistable_history(session: UISession) -> bool:
    return session_has_persistable_history_impl(session)


def persist_session_state(session: UISession) -> None:
    persist_session_state_impl(session, _session_store)


def set_session_generating(session: UISession, is_generating: bool) -> None:
    set_session_generating_impl(session, is_generating)


def persisted_state_to_history_item(state: PersistedSessionState) -> SessionHistoryItem:
    return persisted_state_to_history_item_impl(state)


def hydrate_session_from_state(state: PersistedSessionState) -> UISession:
    deploy_connection_manager = DeployConnectionManager(
        workspace=resolve_workspace_path(state.workspace)
    )
    for connection in state.deploy_connections.values():
        if isinstance(connection, dict):
            deploy_connection_manager.register_connection(connection)

    chat_session, model_name, startup_error, env_file_used, resolved_reasoning_effort = build_chat_session(
        state.workspace,
        state.env_file,
        reasoning_effort=state.reasoning_effort,
        agent_type=state.agent_type,
    )
    interactive_command_session = InteractiveCommandSession(
        workspace=resolve_workspace_path(state.workspace)
    )
    session = UISession(
        session_id=state.session_id,
        model=model_name if chat_session is not None else state.model,
        reasoning_effort=resolved_reasoning_effort if chat_session is not None else state.reasoning_effort,
        workspace=state.workspace,
        mode="agent" if chat_session is not None else state.mode,
        agent_type=state.agent_type,
        phase=state.phase,
        route_state=state.route_state,
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
        code_changes=state.code_changes,
        thoughts=state.thoughts,
        token_usage=state.token_usage,
        cumulative_token_usage=state.cumulative_token_usage,
        max_context_tokens=state.max_context_tokens,
        created_at=state.created_at,
        updated_at=state.updated_at,
        plan_steps=state.plan_steps,
        plan_state=state.plan_state,
        pending_delete_confirmations=state.pending_delete_confirmations,
        pending_commit_confirmations=state.pending_commit_confirmations,
        pending_tag_confirmations=state.pending_tag_confirmations,
        pending_user_input_requests=state.pending_user_input_requests,
        pending_connect_requests=state.pending_connect_requests,
        deploy_connection_manager=deploy_connection_manager,
        deploy_state=state.deploy_state,
    )
    if session.chat_session is not None:
        seed_chat_session_history(session.chat_session, state.history_messages, state.history_tools)
    if session.chat_session is not None and isinstance(session.chat_session.agent, Agent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            deploy_connection_manager=deploy_connection_manager,
        )
        sync_session_runtime_state_for_agent(session)
    return session


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


def normalize_workspace_identifier(workspace_id: str) -> str:
    decoded = unquote(str(workspace_id or "").strip())
    if not decoded:
        raise HTTPException(status_code=400, detail="工作区不能为空。")
    return normalize_workspace_impl(decoded, DEFAULT_WORKSPACE)


@app.get("/api/plugins")
async def get_plugins() -> JSONResponse:
    return JSONResponse({"plugins": list_builtin_plugins()})


@app.get("/api/workspaces")
async def get_workspaces() -> JSONResponse:
    return JSONResponse({"workspaces": list_workspace_options()})


@app.get("/api/workspaces/{workspace_id:path}/kanban/boards")
async def list_kanban_boards(workspace_id: str) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    boards = _kanban_store.list_boards(workspace)
    return JSONResponse({"boards": boards})


@app.post("/api/workspaces/{workspace_id:path}/kanban/boards")
async def create_kanban_board(
    workspace_id: str,
    request: KanbanBoardCreateRequest,
) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    board = _kanban_store.create_board(
        workspace,
        name=request.name,
        description=request.description,
    )
    return JSONResponse({"board": board})


@app.get("/api/workspaces/{workspace_id:path}/kanban/boards/{board_id}")
async def get_kanban_board(workspace_id: str, board_id: str) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    board = _kanban_store.get_board(workspace, board_id)
    return JSONResponse({"board": board})


@app.post("/api/workspaces/{workspace_id:path}/kanban/cards")
async def create_kanban_card(
    workspace_id: str,
    request: KanbanCardCreateRequest,
) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    card = _kanban_store.create_card(
        workspace,
        board_id=request.boardId,
        title=request.title,
        column_id=request.columnId,
        status=request.status,
        description=request.description,
        priority=request.priority,
        labels=request.labels,
        assignee=request.assignee,
    )
    board = _kanban_store.get_board(workspace, str(card["boardId"]))
    return JSONResponse({"card": card, "board": board})


@app.patch("/api/workspaces/{workspace_id:path}/kanban/cards/{card_id}")
async def update_kanban_card(
    workspace_id: str,
    card_id: str,
    request: KanbanCardUpdateRequest,
) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    provided_fields = set(getattr(request, "model_fields_set", set()))
    card = _kanban_store.update_card(
        workspace,
        card_id,
        title=request.title,
        description=request.description,
        priority=request.priority,
        labels=request.labels,
        assignee=request.assignee,
        column_id=request.columnId,
        status=request.status,
        position=request.position,
        ai_state=request.aiState if "aiState" in provided_fields else ...,
    )
    board = _kanban_store.get_board(workspace, str(card["boardId"]))
    return JSONResponse({"card": card, "board": board})


@app.post("/api/workspaces/{workspace_id:path}/kanban/cards/reorder")
async def reorder_kanban_cards(
    workspace_id: str,
    request: KanbanCardReorderRequest,
) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    board = _kanban_store.reorder_cards(
        workspace,
        board_id=request.boardId,
        card_id=request.cardId,
        column_id=request.columnId,
        target_column_id=request.targetColumnId,
        ordered_card_ids=request.orderedCardIds,
    )
    return JSONResponse({"board": board})


@app.delete("/api/workspaces/{workspace_id:path}/kanban/cards/{card_id}")
async def delete_kanban_card(workspace_id: str, card_id: str) -> JSONResponse:
    workspace = normalize_workspace_identifier(workspace_id)
    result = _kanban_store.delete_card(workspace, card_id)
    return JSONResponse(result)


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


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    return JSONResponse(load_settings(ROOT))


@app.put("/api/settings")
async def update_settings(payload: SettingsPayload) -> JSONResponse:
    merged = save_settings(ROOT, payload.model_dump())
    return JSONResponse(merged)


@app.put("/api/sessions/{session_id}/model")
async def switch_session_model(session_id: str, request: SwitchModelRequest) -> JSONResponse:
    session = require_session(session_id)
    model_option = resolve_model_option(request.model, request.env_file)
    model_ref = model_option["envFile"]
    provided_fields = set(getattr(request, "model_fields_set", set()))
    try:
        reasoning_effort = (
            normalize_reasoning_effort(request.reasoning_effort)
            if "reasoning_effort" in provided_fields
            else session.reasoning_effort
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        config, normalized_model_ref = build_agent_config(ROOT, model_ref)
        config.reasoning_effort = reasoning_effort
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = OpenAICompatibleClient(config)
    if session.agent_type == "deploy":
        model = DeployPromptModel(client, workspace=session.workspace)
        tools = build_deploy_tools()
    else:
        model = CodingPromptModel(client, workspace=session.workspace)
        tools = build_coding_tools()
    agent = Agent(
        model=model,
        tools=tools,
        workspace=resolve_workspace_path(session.workspace),
        tool_context_metadata={
            "include_thoughts_in_context": config.include_thoughts_in_context,
            "llm_client": client,
        },
    )
    interactive_command_session = session.interactive_command_session

    session.chat_session = ChatSession(agent=agent)
    seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
    if isinstance(session.chat_session.agent, Agent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            include_thoughts_in_context=config.include_thoughts_in_context,
            deploy_connection_manager=session.deploy_connection_manager,
        )
        sync_session_runtime_state_for_agent(session)
    session.model = config.model
    session.max_context_tokens = infer_model_context_limit(session.model)
    session.reasoning_effort = config.reasoning_effort
    session.env_file = normalized_model_ref
    session.mode = "agent"
    session.startup_error = None
    invalidate_session_context_usage(session)
    session.touch()

    return JSONResponse({
        "model": session.model,
        "modelId": resolve_model_reference_id(session.model, session.env_file),
        "reasoningEffort": session.reasoning_effort,
        "mode": session.mode,
        "agentType": session.agent_type,
        "phase": session.phase,
        "routeState": session.route_state,
        "deployState": session.deploy_state,
        "planState": session.plan_state,
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
    agent_type = normalize_agent_type(request.agent_type)
    requested_env_file = resolve_requested_env_file(request.model, request.env_file)
    try:
        reasoning_effort = normalize_reasoning_effort(request.reasoning_effort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        chat_session, model_name, startup_error, env_file_used, resolved_reasoning_effort = await asyncio.wait_for(
            asyncio.to_thread(
                build_chat_session,
                workspace,
                requested_env_file,
                agent_type,
                reasoning_effort,
            ),
            timeout=30,
        )
    except asyncio.TimeoutError:
        chat_session, model_name, startup_error, env_file_used, resolved_reasoning_effort = (
            None,
            "Demo",
            "初始化模型超时",
            None,
            reasoning_effort,
        )

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
        reasoning_effort=resolved_reasoning_effort,
        workspace=workspace,
        env_file=env_file_used,
        agent_type=agent_type,
        terminal_runtime=TerminalRuntime(workspace=workspace),
        interactive_command_session=interactive_command_session,
        chat_session=chat_session,
        mode="agent" if chat_session is not None else "demo",
        startup_error=startup_error,
        selected_file_path=pick_default_file(workspace),
        open_files=build_default_open_files(workspace),
    )
    if session.chat_session is not None and isinstance(session.chat_session.agent, Agent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            deploy_connection_manager=session.deploy_connection_manager,
        )
        sync_session_runtime_state_for_agent(session)
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
            reasoningEffort=session.reasoning_effort,
            mode=session.mode,
            agentType=session.agent_type,
            phase=session.phase,
            routeState=session.route_state,
            deployState=session.deploy_state,
            planState=session.plan_state,
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
            availableSkills=list_available_skill_summaries(session.workspace),
            codeChanges=session.code_changes,
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
            agentType=session.agent_type,
            phase=session.phase,
            routeState=session.route_state,
            deployState=session.deploy_state,
            planState=session.plan_state,
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
            availableSkills=list_available_skill_summaries(session.workspace),
            codeChanges=session.code_changes,
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


@app.get("/api/files/open")
@app.post("/api/files/open")
async def open_file_in_editor(
    session_id: str | None = Query(None),
    path: str | None = Query(None),
    editor: str | None = Query(None),
    body: dict[str, Any] | None = Body(None),
) -> JSONResponse:
    payload = body if isinstance(body, dict) else {}
    resolved_session_id = str(payload.get("session_id") or session_id or "").strip()
    resolved_path_arg = str(payload.get("path") or path or "").strip()
    resolved_editor = str(payload.get("editor") or editor or "").strip()

    if not resolved_session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    if not resolved_path_arg:
        raise HTTPException(status_code=400, detail="缺少 path")
    if not resolved_editor:
        raise HTTPException(status_code=400, detail="缺少 editor")

    session, target, resolved_path = resolve_workspace_target(resolved_session_id, resolved_path_arg)
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="目标不是文件")

    command = launch_editor_process(editor=resolved_editor, target=target)
    session.selected_file_path = resolved_path
    session.touch()
    return JSONResponse(
        {
            "launched": True,
            "path": resolved_path,
            "absolutePath": str(target),
            "editor": resolved_editor,
            "command": command,
        }
    )


@app.get("/api/sessions/{session_id}/preview")
@app.get("/api/sessions/{session_id}/preview/{preview_path:path}")
async def preview_session_file(session_id: str, preview_path: str = "") -> FileResponse:
    session = require_session(session_id)
    target = resolve_preview_path(preview_path, session.workspace)
    return FileResponse(target)


@app.get("/api/preview/select-bridge.js")
async def get_preview_select_bridge_script() -> Response:
    return Response(
        PREVIEW_SELECT_BRIDGE_SCRIPT,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


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
    session, target, resolved_path = resolve_workspace_target(session_id, path)
    content = body.get("content", "") if body else ""
    try:
        existed_before_save = target.exists()
        before_text = read_text_file(str(target), session.workspace) if existed_before_save else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        session.mark_file_tree_dirty()
        code_change = None
        if (not existed_before_save) or before_text != content:
            code_change = record_code_change(
                session,
                action="added" if not existed_before_save else "modified",
                path=target,
                before_text=before_text,
                after_text=content,
                source="editor",
                summary=f"{'手动新增' if not existed_before_save else '手动保存'} {relative_workspace_path(target, session.workspace)}",
            )
        session.touch()
        return JSONResponse({"saved": True, "path": resolved_path, "codeChange": code_change})
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
        target = Path(normalize_relative_path(filename, session.workspace))
        before_text = read_text_file(str(target), session.workspace)
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
        code_change = record_code_change(
            session,
            action="deleted",
            path=target,
            before_text=before_text,
            after_text="",
            source="agent",
            tool_call_id=tool_id,
            assistant_id=assistant_id or None,
            turn_index=current_agent_turn_index(session),
            step_index=pending.get("step_index") if isinstance(pending.get("step_index"), int) else None,
        )
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
                "codeChange": code_change,
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
    assistant_id = str(pending.get("assistant_id") or "").strip()
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


@app.post("/api/sessions/{session_id}/tools/{tool_id}/connect")
async def submit_connect_tool(
    session_id: str,
    tool_id: str,
    request: ConnectToolSubmitRequest,
) -> JSONResponse:
    session = require_session(session_id)
    pending = session.pending_connect_requests.get(tool_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="未找到待填写的 connect 请求")

    deploy_manager = session.deploy_connection_manager
    if deploy_manager is None:
        raise HTTPException(status_code=500, detail="当前会话缺少 deploy connection manager")

    values = request.values if isinstance(request.values, dict) else {}
    host = str(values.get("host") or "").strip()
    username = str(values.get("username") or "").strip()
    password = str(values.get("password") or "")
    root_path = str(values.get("root_path") or "").strip()
    display_name = str(values.get("display_name") or "").strip()
    description = str(values.get("description") or "").strip()
    extra_info = str(values.get("extra_info") or "").strip()
    if not root_path:
        raise HTTPException(status_code=400, detail="root_path 为必填项")
    if host and (not username or not password):
        raise HTTPException(status_code=400, detail="远程连接必须提供 username 和 password")

    try:
        connection = deploy_manager.create_connection(
            root_path=root_path,
            display_name=display_name,
            description=description,
            extra_info=extra_info,
            host=host,
            username=username,
            password=password,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session.pending_connect_requests.pop(tool_id, None)
    assistant_id = str(pending.get("assistant_id") or "").strip()
    can_continue = bool(assistant_id and session.chat_session is not None)
    input_request = pending.get("request") if isinstance(pending.get("request"), dict) else None
    output = {
        **connection,
        "message": (
            f"已建立 deploy session {connection['session_id']}，"
            + (f"服务器：{connection['host']}" if connection.get("host") else f"根目录：{connection['root_path']}")
        ),
    }
    tool_record = {
        "id": tool_id,
        "name": str(pending.get("tool_name") or "connect"),
        "output": output,
        "success": True,
        "state": "output-available",
        "inputRequest": input_request,
    }
    session.history_tools = upsert_tool(session.history_tools, tool_record)
    if assistant_id:
        update_assistant_tool_call(
            session,
            assistant_id,
            tool_id,
            lambda existing: {
                **existing,
                **tool_record,
            },
        )
    record_confirmation_result_for_agent(
        session,
        (
            "[内部连接结果] connect 已建立 deploy session："
            f"{connection['session_id']} -> {connection['root_path']}"
        ),
    )
    set_session_phase(session, "connected")
    update_deploy_state(
        session,
        active_session_id=connection["session_id"],
        active_root_path=connection["root_path"],
        active_display_name=connection["display_name"],
        active_host=connection.get("host") or None,
        active_username=connection.get("username") or None,
        active_extra_info=connection.get("extra_info") or None,
        pending_tool_id=None,
        pending_tool_name=None,
        pending_input_kind=None,
        last_tool_name=str(pending.get("tool_name") or "connect"),
        last_tool_state="completed",
        last_error=None,
        last_message=str(output.get("message") or ""),
    )
    session.touch()
    return JSONResponse(
        {
            "id": tool_id,
            "name": str(pending.get("tool_name") or "connect"),
            "output": output,
            "success": True,
            "state": "output-available",
            "assistantId": assistant_id,
            "shouldContinue": can_continue,
            "phase": session.phase,
            "deployState": session.deploy_state,
        }
    )


def _normalize_tool_input_answers(
    input_request: dict[str, Any],
    request: ToolInputSubmitRequest,
) -> list[dict[str, Any]]:
    raw_questions = input_request.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise HTTPException(status_code=400, detail="当前输入请求缺少 questions。")

    questions_by_id: dict[str, dict[str, Any]] = {}
    question_order: list[str] = []
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            continue
        question_id = str(raw_question.get("id") or "").strip()
        if not question_id:
            continue
        questions_by_id[question_id] = raw_question
        question_order.append(question_id)

    answers_by_id = {answer.questionId.strip(): answer for answer in request.answers if answer.questionId.strip()}
    normalized_answers: list[dict[str, Any]] = []

    unknown_answers = sorted(set(answers_by_id) - set(questions_by_id))
    if unknown_answers:
        raise HTTPException(status_code=400, detail=f"存在未知问题 ID：{', '.join(unknown_answers)}")

    for question_id in question_order:
        question = questions_by_id[question_id]
        answer = answers_by_id.get(question_id)
        question_type = str(question.get("type") or "").strip()
        prompt = str(question.get("prompt") or "").strip()
        required = bool(question.get("required", True))
        other_text = ""
        selected_option_ids: list[str] = []
        free_text = ""

        if answer is not None:
            other_text = str(answer.otherText or "").strip()
            selected_option_ids = [option_id.strip() for option_id in answer.selectedOptionIds if option_id.strip()]
            free_text = str(answer.text or "").strip()

        if question_type == "short_text":
            if required and not free_text:
                raise HTTPException(status_code=400, detail=f"问题「{prompt}」尚未回答。")
            normalized_answers.append(
                {
                    "questionId": question_id,
                    "type": question_type,
                    "prompt": prompt,
                    "text": free_text,
                    "otherText": other_text or None,
                }
            )
            continue

        raw_options = question.get("options")
        options = raw_options if isinstance(raw_options, list) else []
        options_by_id = {
            str(option.get("id") or "").strip(): option
            for option in options
            if isinstance(option, dict) and str(option.get("id") or "").strip()
        }

        invalid_option_ids = [option_id for option_id in selected_option_ids if option_id not in options_by_id]
        if invalid_option_ids:
            raise HTTPException(
                status_code=400,
                detail=f"问题「{prompt}」包含未知选项：{', '.join(invalid_option_ids)}",
            )
        if question_type == "single_choice" and len(selected_option_ids) > 1:
            raise HTTPException(status_code=400, detail=f"问题「{prompt}」只能选择一个选项。")
        if required and not selected_option_ids and not other_text:
            raise HTTPException(status_code=400, detail=f"问题「{prompt}」尚未回答。")

        normalized_answers.append(
            {
                "questionId": question_id,
                "type": question_type,
                "prompt": prompt,
                "selectedOptionIds": selected_option_ids,
                "selectedOptions": [
                    {
                        "id": option_id,
                        "label": str(options_by_id[option_id].get("label") or "").strip(),
                        "description": str(options_by_id[option_id].get("description") or "").strip(),
                    }
                    for option_id in selected_option_ids
                ],
                "otherText": other_text or None,
                "text": free_text or None,
            }
        )

    return normalized_answers


def _format_tool_input_answers_for_agent(
    title: str,
    answers: list[dict[str, Any]],
) -> str:
    lines = [f"[用户回答] {title}".strip()]
    for answer in answers:
        prompt = str(answer.get("prompt") or answer.get("questionId") or "未命名问题").strip()
        answer_type = str(answer.get("type") or "").strip()
        if answer_type == "short_text":
            value = str(answer.get("text") or answer.get("otherText") or "").strip() or "(未填写)"
        else:
            labels = [
                str(option.get("label") or "").strip()
                for option in answer.get("selectedOptions", [])
                if isinstance(option, dict) and str(option.get("label") or "").strip()
            ]
            other_text = str(answer.get("otherText") or "").strip()
            if other_text:
                labels.append(f"其他：{other_text}")
            value = "；".join(labels) if labels else "(未填写)"
        lines.append(f"- {prompt}: {value}")
    return "\n".join(lines)


def _resolve_plan_payload(
    session: UISession,
    request: PlanSubmitRequest,
) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    base_plan = (
        plan_state.get("draft")
        if isinstance(plan_state.get("draft"), dict)
        else plan_state.get("last_submitted_plan")
        if isinstance(plan_state.get("last_submitted_plan"), dict)
        else {}
    )
    provided_fields = set(getattr(request, "model_fields_set", set()))

    def choose_text(field_name: str, fallback_key: str) -> str:
        if field_name in provided_fields:
            return str(getattr(request, field_name) or "").strip()
        return str(base_plan.get(fallback_key) or "").strip()

    title = choose_text("title", "title")
    summary = choose_text("summary", "summary")
    overview = choose_text("overview", "overview")
    markdown = choose_text("markdown", "markdown")
    if "keySteps" in provided_fields:
        key_steps = [item.strip() for item in request.keySteps if isinstance(item, str) and item.strip()]
    else:
        raw_key_steps = base_plan.get("keySteps")
        key_steps = [item.strip() for item in raw_key_steps if isinstance(item, str) and item.strip()] if isinstance(raw_key_steps, list) else []

    if not title or not summary or not overview or not key_steps or not markdown:
        raise HTTPException(status_code=400, detail="提交计划时必须至少提供 title、summary、overview、keySteps、markdown，或先生成计划草案。")

    return {
        "title": title,
        "summary": summary,
        "overview": overview,
        "keySteps": key_steps,
        "markdown": markdown,
    }


def _derive_plan_title_from_markdown(markdown: str, fallback: str = "计划草案") -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
        break
    return fallback


def update_current_plan_draft(
    session: UISession,
    *,
    title: str | None,
    markdown: str,
) -> dict[str, Any]:
    normalized_markdown = str(markdown or "").strip()
    if not normalized_markdown:
        raise HTTPException(status_code=400, detail="markdown 不能为空。")

    plan_state = normalize_plan_state(session.plan_state)
    base_plan = (
        plan_state.get("draft")
        if isinstance(plan_state.get("draft"), dict)
        else plan_state.get("last_submitted_plan")
        if isinstance(plan_state.get("last_submitted_plan"), dict)
        else {}
    )
    next_plan = dict(base_plan) if isinstance(base_plan, dict) else {}
    resolved_title = str(title or next_plan.get("title") or "").strip() or _derive_plan_title_from_markdown(normalized_markdown)

    next_plan["title"] = resolved_title
    next_plan["markdown"] = normalized_markdown
    next_plan["summary"] = str(next_plan.get("summary") or "").strip()
    next_plan["overview"] = str(next_plan.get("overview") or "").strip()
    raw_key_steps = next_plan.get("keySteps")
    next_plan["keySteps"] = (
        [str(item).strip() for item in raw_key_steps if str(item).strip()]
        if isinstance(raw_key_steps, list)
        else []
    )

    status = str(plan_state.get("status") or "idle").strip().lower()
    update_plan_state(
        session,
        draft=next_plan,
        status="draft_ready" if status != "submitted" else status,
    )
    sync_session_runtime_state_for_agent(session)
    session.touch()
    return next_plan


def _build_coding_input_from_plan(plan: dict[str, Any]) -> str:
    lines = [
        "请根据下面这份已经确认的计划开始进入编码实现阶段。",
        "除非发现计划与现有代码现实冲突，否则不要重新回到需求澄清模式。",
        "",
        f"# {str(plan.get('title') or '').strip()}",
        str(plan.get("summary") or "").strip(),
        "",
        "## 总览",
        str(plan.get("overview") or "").strip(),
        "",
        "## 关键步骤",
    ]

    key_steps = plan.get("keySteps")
    if isinstance(key_steps, list):
        lines.extend(f"- {str(step).strip()}" for step in key_steps if str(step).strip())

    lines.extend([
        "",
        "## 详细草案",
        str(plan.get("markdown") or "").strip(),
    ])

    return "\n".join(line for line in lines if line is not None).strip()


def activate_plan_for_coding(session: UISession, request: PlanSubmitRequest) -> tuple[dict[str, Any], str]:
    plan = _resolve_plan_payload(session, request)
    coding_input = _build_coding_input_from_plan(plan)

    session.history_messages = []
    session.history_tools = []
    session.thoughts = []
    invalidate_session_context_usage(session)
    session.pending_user_input_requests.clear()
    session.pending_connect_requests.clear()
    session.pending_delete_confirmations.clear()
    session.pending_commit_confirmations.clear()
    session.pending_tag_confirmations.clear()
    update_plan_state(
        session,
        status="submitted",
        draft=plan,
        last_submitted_plan=plan,
        pending_coding_input=coding_input,
    )
    session.route_state = normalize_route_state(
        {
            "agentType": "coding",
            "confidence": 1.0,
            "reason": "计划已提交，自动切换到编码智能体执行计划。",
            "source": "forced",
            "fallbackUsed": False,
            "keepCurrentAgent": session.agent_type == "coding",
            "previousAgentType": session.agent_type,
        }
    )
    rebuild_chat_session_for_agent_type(session, "coding")
    session.plan_steps = []
    set_session_phase(session, "idle")
    sync_session_runtime_state_for_agent(session)
    session.touch()
    return plan, coding_input


@app.get("/api/sessions/{session_id}/plan-draft/current")
async def get_current_plan_draft(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    plan_state = normalize_plan_state(session.plan_state)
    plan = (
        plan_state.get("draft")
        if isinstance(plan_state.get("draft"), dict)
        else plan_state.get("last_submitted_plan")
        if isinstance(plan_state.get("last_submitted_plan"), dict)
        else None
    )
    if not isinstance(plan, dict):
        raise HTTPException(status_code=404, detail="当前会话没有可读取的计划草案。")

    return JSONResponse(
        {
            "ok": True,
            "plan": plan,
            "planState": session.plan_state,
        }
    )


@app.post("/api/sessions/{session_id}/plan-draft")
async def save_current_plan_draft(
    session_id: str,
    request: PlanDraftUpdateRequest,
) -> JSONResponse:
    session = require_session(session_id)
    plan = update_current_plan_draft(
        session,
        title=request.title,
        markdown=request.markdown,
    )
    return JSONResponse(
        {
            "ok": True,
            "plan": plan,
            "planState": session.plan_state,
        }
    )


@app.post("/api/sessions/{session_id}/tools/{tool_id}/input")
async def submit_tool_input(
    session_id: str,
    tool_id: str,
    request: ToolInputSubmitRequest,
) -> JSONResponse:
    session = require_session(session_id)
    pending = session.pending_user_input_requests.pop(tool_id, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="未找到待填写的输入请求")

    input_request = pending.get("request")
    if not isinstance(input_request, dict):
        raise HTTPException(status_code=400, detail="当前输入请求结构无效")

    assistant_id = str(pending.get("assistant_id") or "").strip()
    tool_name = str(pending.get("tool_name") or "ask_plan_questions")
    title = str(input_request.get("title") or tool_name).strip()
    answers = _normalize_tool_input_answers(input_request, request)
    output = {
        "message": "已收到用户回答，可以继续完善计划。",
        "kind": str(input_request.get("kind") or pending.get("kind") or "plan_questions"),
        "title": title,
        "answers": answers,
    }
    tool_record = {
        "id": tool_id,
        "name": tool_name,
        "output": output,
        "success": True,
        "state": "output-available",
        "inputRequest": input_request,
    }
    session.history_tools = upsert_tool(session.history_tools, tool_record)
    if assistant_id:
        update_assistant_tool_call(
            session,
            assistant_id,
            tool_id,
            lambda existing: {
                **existing,
                **tool_record,
            },
        )
    record_tool_result_for_agent(
        session,
        tool_id=tool_id,
        tool_name=tool_name,
        output=output,
        success=True,
        state="output-available",
    )
    record_confirmation_result_for_agent(
        session,
        _format_tool_input_answers_for_agent(title, answers),
    )
    if session.agent_type == "plan":
        set_session_phase(session, "clarifying")
        update_plan_state(session, status="clarifying")
    session.touch()
    return JSONResponse(
        {
            "id": tool_id,
            "name": tool_name,
            "output": output,
            "success": True,
            "state": "output-available",
            "assistantId": assistant_id,
            "shouldContinue": bool(assistant_id),
            "phase": session.phase,
            "planState": session.plan_state,
        }
    )


@app.post("/api/sessions/{session_id}/plan/submit")
async def submit_plan(
    session_id: str,
    request: PlanSubmitRequest,
) -> JSONResponse:
    session = require_session(session_id)
    plan, coding_input = activate_plan_for_coding(session, request)
    return JSONResponse(
        {
            "ok": True,
            "agentType": session.agent_type,
            "phase": session.phase,
            "routeState": session.route_state,
            "planState": session.plan_state,
            "plan": plan,
            "codingInput": coding_input,
            "shouldStartCoding": True,
        }
    )


@app.post("/api/sessions/{session_id}/tasks")
async def create_task_endpoint(
    session_id: str,
    request: CreateTaskRequest,
) -> JSONResponse:
    session = require_session(session_id)
    task = create_task_in_session(
        session,
        title=request.title,
        summary=request.summary,
        steps=[{"title": step.title, "summary": step.summary} for step in request.steps],
        source=session.agent_type,
    )
    return JSONResponse(
        {
            "ok": True,
            "task_id": task["id"],
            "step_ids": [str(step.get("id") or "") for step in task.get("steps", []) if isinstance(step, dict)],
            "task": task,
            "planState": session.plan_state,
            "planSteps": session.plan_steps,
        }
    )


@app.post("/api/sessions/{session_id}/tasks/finish")
async def finish_task_endpoint(
    session_id: str,
    request: FinishTaskRequest,
) -> JSONResponse:
    session = require_session(session_id)
    result = finish_task_step_in_session(session, request.step_id)
    return JSONResponse(
        {
            "ok": True,
            **result,
            "planState": session.plan_state,
            "planSteps": session.plan_steps,
        }
    )


@app.get("/api/sessions/{session_id}/tasks/status")
async def get_task_status_endpoint(
    session_id: str,
    task_id: str | None = Query(None),
) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(
        {
            "ok": True,
            **build_task_status_payload(session, task_id=task_id),
            "planState": session.plan_state,
            "planSteps": session.plan_steps,
        }
    )


@app.get("/api/sessions/{session_id}/deploy/connections")
async def list_deploy_connections(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    manager = session.deploy_connection_manager
    if manager is None:
        return JSONResponse({"connections": []})
    return JSONResponse({"connections": manager.list_connections()})


@app.get("/api/sessions/{session_id}/context")
async def get_session_context(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    return JSONResponse(session.context_snapshot().model_dump())


@app.post("/api/sessions/{session_id}/context/compress")
async def compress_session_context_endpoint(
    session_id: str,
    request: SessionContextCompressionRequest,
) -> JSONResponse:
    session = require_session(session_id)
    if request.mode == "apply":
        if session.is_generating:
            raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能压缩上下文")
        if _session_has_pending_context_interaction(session):
            raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能压缩上下文")
    response = await asyncio.to_thread(compress_session_context, session, request)
    return JSONResponse(response.model_dump())


@app.post("/api/sessions/{session_id}/fork")
async def fork_session_endpoint(session_id: str) -> JSONResponse:
    session = require_session(session_id)
    if session.is_generating:
        raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能派生分支")
    if _session_has_pending_context_interaction(session):
        raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能派生分支")
    forked_session = await asyncio.to_thread(fork_session_from_current, session)
    snapshot = await asyncio.to_thread(forked_session.snapshot)
    return JSONResponse(snapshot.model_dump())


@app.post("/api/sessions/{session_id}/restore")
async def restore_session_endpoint(
    session_id: str,
    request: SessionRestoreRequest,
) -> JSONResponse:
    session = require_session(session_id)
    if session.is_generating:
        raise HTTPException(status_code=409, detail="会话正在生成内容，暂时不能还原对话")
    if _session_has_pending_context_interaction(session):
        raise HTTPException(status_code=409, detail="当前存在待处理交互，暂时不能还原对话")
    snapshot = await asyncio.to_thread(restore_session_to_message, session, request.messageId)
    return JSONResponse(snapshot.model_dump())


@app.get("/api/sessions/{session_id}/terminal")
async def get_session_terminal(
    session_id: str,
    include_output: bool = Query(False),
    include_file_tree: bool = Query(False),
    include_processes: bool = Query(False),
) -> JSONResponse:
    session = require_session(session_id)
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
    session = require_session(session_id)
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


@app.websocket("/api/sessions/{session_id}/terminal/ws")
async def session_terminal_websocket(
    websocket: WebSocket,
    session_id: str,
) -> None:
    session = require_session(session_id)
    if session.terminal_runtime is None:
        await websocket.close(code=1011, reason="terminal 不存在")
        return

    await websocket.accept()
    loop = asyncio.get_running_loop()
    output_queue: asyncio.Queue[str | None] = asyncio.Queue()
    send_lock = asyncio.Lock()

    def enqueue_output(chunk: str) -> None:
        loop.call_soon_threadsafe(output_queue.put_nowait, chunk)

    unsubscribe = session.terminal_runtime.read_loop(enqueue_output)

    async def send_terminal_message(message: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def send_terminal_status() -> None:
        snapshot = session.terminal_runtime.snapshot(
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
        snapshot = session.terminal_runtime.snapshot(
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
        session.terminal_output = session.terminal_runtime.snapshot(
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
                session.terminal_runtime.write(str(message.get("data") or ""))
                continue
            elif message_type == "resize":
                try:
                    cols = int(message.get("cols") or 0)
                    rows = int(message.get("rows") or 0)
                except (TypeError, ValueError):
                    continue
                session.terminal_runtime.resize(cols, rows)
                continue
            elif message_type == "clear":
                session.terminal_runtime.clear()
                session.terminal_output = ""
                await send_terminal_message({"type": "clear"})
                await send_terminal_status()
            elif message_type == "interrupt":
                if not session.terminal_runtime.interrupt():
                    await send_terminal_message(
                        {"type": "error", "message": "当前终端后端不支持 Ctrl+C 中断"}
                    )
                await send_terminal_status()
            else:
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


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatStreamRequest,
    protocol: str = Query("ui-message"),
) -> StreamingResponse:
    session = require_session(request.session_id)
    session.cancel_event.clear()
    original_user_message = request.message.strip()
    if not original_user_message:
        raise HTTPException(status_code=400, detail="message 不能为空")
    user_message, active_skills = resolve_message_skills(
        session.workspace,
        original_user_message,
        request.skills,
    )
    if not user_message:
        raise HTTPException(status_code=400, detail="请在选择 skill 后补充具体任务。")
    forced_agent_type = None
    requested_agent_mode = str(request.agent_mode or "").strip().lower()
    if requested_agent_mode and requested_agent_mode != "auto":
        forced_agent_type = normalize_agent_type(requested_agent_mode)
    route_session_for_user_message(session, user_message, forced_agent_type=forced_agent_type)
    if session.chat_session is not None:
        session.chat_session.state.data["active_skills"] = active_skills
    if session.agent_type == "coding" and session.plan_state.get("pending_coding_input"):
        update_plan_state(session, pending_coding_input=None)

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
                    "content": original_user_message,
                },
            }
        )
        session.history_messages.append(
            {"id": user_message_id, "role": "user", "content": original_user_message}
        )
        session.touch()

        producer = asyncio.create_task(
            run_demo_stream(session, user_message, queue)
            if session.chat_session is None
            else run_agent_stream(
                session,
                user_message,
                queue,
                history_user_message=original_user_message,
            )
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
    if session.chat_session is None:
        raise HTTPException(status_code=409, detail="当前会话不支持 continue")
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


def normalize_agent_type(agent_type: str | None) -> str:
    normalized = str(agent_type or "coding").strip().lower()
    if normalized not in {"coding", "deploy", "plan"}:
        raise HTTPException(status_code=400, detail=f"不支持的 agent_type: {agent_type}")
    return normalized


def attach_agent_runtime_metadata(
    agent: Agent,
    session_id: str,
    interactive_command_session: InteractiveCommandSession | None,
    cancel_event: threading.Event | None = None,
    include_thoughts_in_context: bool | None = None,
    deploy_connection_manager: DeployConnectionManager | None = None,
) -> None:
    agent.tool_context_metadata["session_id"] = session_id
    agent.tool_context_metadata["backend_base_url"] = BACKEND_BASE_URL
    agent.tool_context_metadata["project_root"] = str(ROOT)
    if include_thoughts_in_context is not None:
        agent.tool_context_metadata["include_thoughts_in_context"] = include_thoughts_in_context
    if interactive_command_session is not None:
        agent.tool_context_metadata["interactive_command_session"] = interactive_command_session
    if cancel_event is not None:
        agent.tool_context_metadata["cancel_event"] = cancel_event
    if deploy_connection_manager is not None:
        agent.tool_context_metadata["deploy_connection_manager"] = deploy_connection_manager


def build_chat_session(
    workspace: str,
    env_file: str | None = None,
    agent_type: str = "coding",
    reasoning_effort: str | None = None,
) -> tuple[ChatSession | None, str, str | None, str | None, str | None]:
    try:
        config, normalized_model_ref = build_agent_config(ROOT, env_file)
        if reasoning_effort is not None:
            config.reasoning_effort = normalize_reasoning_effort(reasoning_effort)
        client = OpenAICompatibleClient(config)
        resolved_workspace = resolve_workspace_path(workspace)
        if agent_type == "deploy":
            model = DeployPromptModel(client, workspace=workspace)
            tools = build_deploy_tools()
        elif agent_type == "plan":
            model = PlanPromptModel(client, workspace=workspace)
            tools = build_plan_tools()
        else:
            model = CodingPromptModel(client, workspace=workspace)
            tools = build_coding_tools()
        agent = Agent(
            model=model,
            tools=tools,
            workspace=resolved_workspace,
            tool_context_metadata={
                "include_thoughts_in_context": config.include_thoughts_in_context,
                "project_root": str(ROOT),
                "llm_client": client,
            },
        )
        return ChatSession(agent=agent), config.model, None, normalized_model_ref, config.reasoning_effort
    except Exception as exc:  # noqa: BLE001 - 需要把启动失败原因回传给前端
        return None, "Demo", str(exc), None, None


async def run_agent_stream(
    session: UISession,
    user_message: str | None,
    queue: asyncio.Queue[dict[str, Any] | None],
    assistant_id: str | None = None,
    resume_existing_turn: bool = False,
    history_user_message: str | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    assistant_id = assistant_id or uuid.uuid4().hex
    streamed_assistant_text = ""
    assistant_stream_started = False
    tool_before_snapshots: dict[str, dict[str, str]] = {}
    reset_phase_for_new_turn(session)
    sync_session_runtime_state_for_agent(session)
    if user_message is not None:
        ensure_user_message_recorded(session, history_user_message or user_message)
    set_session_generating(session, True)

    await queue.put(
        {
            "type": "assistant_started",
            "payload": {
                "id": assistant_id,
            },
        }
    )

    def _session_state_event() -> dict[str, Any]:
        return {
            "type": "data-session-state",
            "payload": {
                "assistant_id": assistant_id,
                "data": build_session_state_payload(session),
            },
        }

    await queue.put(_session_state_event())
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

        if event.type == "usage":
            merge_session_token_usage(session, event.usage)
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
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
            before_snapshots = capture_code_change_before_snapshots(
                session,
                tool_name=event.tool_call.name,
                tool_arguments=event.tool_call.arguments,
            )
            if before_snapshots:
                tool_before_snapshots[tool_id] = before_snapshots
            update_plan_steps_for_tool(session, event.step_index, event.tool_call.name)
            if event.tool_call.name == "read_file":
                maybe_filename = event.tool_call.arguments.get("filename")
                maybe_path = maybe_filename if isinstance(maybe_filename, str) else event.tool_call.arguments.get("path")
                if isinstance(maybe_path, str):
                    session.selected_file_path = normalize_relative_path(maybe_path, session.workspace)
            if session.agent_type == "deploy":
                tool_name = event.tool_call.name
                update_deploy_state(
                    session,
                    pending_tool_id=tool_id,
                    pending_tool_name=tool_name,
                    last_tool_name=tool_name,
                    last_tool_state="running",
                    last_error=None,
                )
                if tool_name == "connect":
                    set_session_phase(session, "awaiting_connect_input")
                elif tool_name in {"list_files", "read_file"}:
                    set_session_phase(session, "exploring")
                elif tool_name in {"transfer_files", "execute"}:
                    set_session_phase(session, "executing")
                if tool_name == "transfer_files":
                    update_deploy_state(
                        session,
                        last_command=None,
                        last_command_cwd=str(event.tool_call.arguments.get("target_dir") or "."),
                        last_exit_code=None,
                    )
                elif tool_name == "execute":
                    update_deploy_state(
                        session,
                        last_command=str(event.tool_call.arguments.get("command") or ""),
                        last_command_cwd=str(event.tool_call.arguments.get("cwd") or "."),
                    )
            elif session.agent_type == "plan":
                tool_name = event.tool_call.name
                if tool_name == "ask_plan_questions":
                    set_session_phase(session, "awaiting_user_input")
                    update_plan_state(session, status="awaiting_user_input")
                elif tool_name == "save_plan":
                    set_session_phase(session, "planning")
                    update_plan_state(session, status="planning")
                else:
                    set_session_phase(session, "researching")
                    update_plan_state(session, status="researching")
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
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
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
            before_snapshots = tool_before_snapshots.pop(tool_id, None)
            terminal_output = extract_terminal_output(output)
            preview_url = extract_preview_url(output)
            raw_requires_confirmation = bool(
                (event.tool_result.name == "delete_file"
                 or event.tool_result.name == "git_commit"
                 or event.tool_result.name == "git_tag")
                and isinstance(output, dict)
                and output.get("requires_confirmation") is True
            )
            auto_approve_enabled = bool(load_settings(ROOT).get("autoApprove"))
            if raw_requires_confirmation and auto_approve_enabled:
                approval = {"id": tool_id, "approved": True}
                tool_success = True
                requires_confirmation = False
                if event.tool_result.name == "delete_file" and isinstance(output, dict):
                    filename = str(output.get("filename") or "").strip()
                    if filename:
                        try:
                            target = Path(normalize_relative_path(filename, session.workspace))
                            before_text = read_text_file(str(target), session.workspace)
                            output = delete_file_in_workspace(filename, resolve_workspace_path(session.workspace))
                            session.mark_file_tree_dirty()
                            if session.selected_file_path == normalize_relative_path(filename, session.workspace):
                                session.selected_file_path = None
                            record_code_change(
                                session,
                                action="deleted",
                                path=target,
                                before_text=before_text,
                                after_text="",
                                source="agent",
                                tool_call_id=tool_id,
                                assistant_id=assistant_id or None,
                                turn_index=current_agent_turn_index(session),
                                step_index=event.step_index,
                            )
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] delete_file 已自动执行：{filename}")
                elif event.tool_result.name == "git_commit" and isinstance(output, dict):
                    commit_message = str(output.get("commit_message") or "").strip()
                    if commit_message:
                        try:
                            output = execute_git_commit(commit_message, resolve_workspace_path(session.workspace))
                            session.mark_file_tree_dirty()
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] git_commit 已自动执行：{commit_message}")
                elif event.tool_result.name == "git_tag" and isinstance(output, dict):
                    tag_name = str(output.get("tag") or "").strip()
                    tag_message = str(output.get("tag_message") or f"Release {tag_name}")
                    if tag_name:
                        try:
                            output = execute_git_tag(tag_name, tag_message, resolve_workspace_path(session.workspace))
                        except Exception:
                            pass
                    record_confirmation_result_for_agent(session, f"[自动确认] git_tag 已自动执行：{tag_name}")
            else:
                requires_confirmation = raw_requires_confirmation
                approval = {"id": tool_id} if requires_confirmation else None
                tool_success = None if requires_confirmation else event.tool_result.success
            requires_user_input = bool(
                isinstance(output, dict)
                and output.get("requires_user_input") is True
            )
            if event.tool_result.name in {"execute", "excecute", "terminal_input", "terminal_wait"} and terminal_output is not None:
                session.terminal_output = terminal_output
            if event.tool_result.name in {"write_file", "replace_file", "apply_patch"} or (
                event.tool_result.name == "delete_file" and not requires_confirmation
            ):
                session.mark_file_tree_dirty()
            if event.tool_result.name == "open_browser" and preview_url is not None:
                session.preview_url = preview_url
            tool_state = (
                "approval-requested"
                if requires_confirmation
                else "input-requested"
                if requires_user_input
                else ("completed" if event.tool_result.success else "error")
            )
            input_request = None
            if requires_confirmation and isinstance(output, dict):
                if event.tool_result.name == "delete_file":
                    session.pending_delete_confirmations[tool_id] = {
                        "filename": str(output.get("filename") or ""),
                        "assistant_id": assistant_id,
                        "step_index": event.step_index,
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
            elif requires_user_input and isinstance(output, dict):
                input_request = {
                    "id": tool_id,
                    "kind": str(output.get("input_kind") or event.tool_result.name),
                    "title": str(output.get("title") or ""),
                    "message": str(output.get("message") or ""),
                    "fields": output.get("fields") if isinstance(output.get("fields"), list) else [],
                    "questions": output.get("questions") if isinstance(output.get("questions"), list) else [],
                }
                pending_payload = {
                    "assistant_id": assistant_id,
                    "tool_name": event.tool_result.name,
                    "request": input_request,
                }
                if session.agent_type == "plan":
                    session.pending_user_input_requests[tool_id] = pending_payload
                else:
                    session.pending_connect_requests[tool_id] = pending_payload
            if session.agent_type == "deploy":
                tool_name = event.tool_result.name
                exit_code = extract_command_exit_code(output)
                deploy_updates: dict[str, Any] = {
                    "last_tool_name": tool_name,
                    "last_tool_state": tool_state,
                    "last_message": (
                        str(output.get("message") or "").strip()
                        if isinstance(output, dict)
                        else compact_text(str(output), 200)
                    )
                    or None,
                }
                if tool_name == "execute":
                    deploy_updates["last_exit_code"] = exit_code
                    if exit_code is not None and exit_code != 0:
                        deploy_updates["last_error"] = f"命令退出码为 {exit_code}"
                elif tool_name == "transfer_files":
                    deploy_updates["last_exit_code"] = None
                if requires_user_input:
                    set_session_phase(session, "awaiting_connect_input")
                    deploy_updates.update(
                        {
                            "pending_tool_id": tool_id,
                            "pending_tool_name": tool_name,
                            "pending_input_kind": str(input_request.get("kind") if input_request else ""),
                        }
                    )
                else:
                    deploy_updates.update(
                        {
                            "pending_tool_id": None,
                            "pending_tool_name": None,
                            "pending_input_kind": None,
                        }
                    )
                    if not event.tool_result.success:
                        set_session_phase(session, "failed")
                        deploy_updates["last_error"] = event.tool_result.error_message
                    elif tool_name in {"list_files", "read_file"}:
                        set_session_phase(session, "exploring")
                    elif tool_name == "transfer_files":
                        set_session_phase(session, "connected")
                    elif tool_name == "execute":
                        set_session_phase(session, "failed" if exit_code not in (None, 0) else "verifying")
                    elif tool_name == "connect":
                        set_session_phase(session, "connected")
                update_deploy_state(session, **deploy_updates)
            elif session.agent_type == "plan":
                tool_name = event.tool_result.name
                if requires_user_input:
                    set_session_phase(session, "awaiting_user_input")
                    update_plan_state(session, status="awaiting_user_input")
                elif not event.tool_result.success:
                    set_session_phase(session, "planning")
                    update_plan_state(session, status="clarifying")
                elif tool_name == "save_plan" and isinstance(output, dict) and isinstance(output.get("plan"), dict):
                    set_session_phase(session, "plan_ready")
                    update_plan_state(
                        session,
                        draft=output.get("plan"),
                        status="draft_ready",
                    )
                elif tool_name in {"search_web", "fetch_url_content", "list_file", "grep_file", "read_file"}:
                    set_session_phase(session, "researching")
                    update_plan_state(session, status="researching")
                else:
                    set_session_phase(session, "planning")
                    update_plan_state(session, status="clarifying")
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
                "inputRequest": input_request,
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
            if event.tool_result.success and not requires_confirmation and not requires_user_input:
                code_change_records = code_change_records_from_tool_result(
                    session,
                    tool_name=event.tool_result.name,
                    tool_arguments=event.tool_call.arguments,
                    output=output,
                    tool_call_id=tool_id,
                    assistant_id=assistant_id,
                    step_index=event.step_index,
                    before_snapshots=before_snapshots,
                )
                for record in code_change_records:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {
                            "type": "data-code-change",
                            "payload": {
                                "assistant_id": assistant_id,
                                "data": record,
                            },
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
                        "input_request": input_request,
                    },
                },
            )
            if event.tool_result.name in {"create_task", "finish_task", "get_task_status"}:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "plan_steps",
                        "payload": {
                            "steps": session.plan_steps,
                        },
                    },
                )
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())
            return

        if event.type in {"final", "turn_finished", "limit_reached"}:
            if session.agent_type == "deploy" and not session.pending_connect_requests and session.phase != "failed":
                set_session_phase(session, "completed")
                update_deploy_state(
                    session,
                    pending_tool_id=None,
                    pending_tool_name=None,
                    pending_input_kind=None,
                )
            if session.agent_type == "plan" and not session.pending_user_input_requests and session.plan_state.get("draft"):
                set_session_phase(session, "plan_ready")
                update_plan_state(session, status="draft_ready")
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
            loop.call_soon_threadsafe(queue.put_nowait, _session_state_event())

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
        if session.agent_type == "deploy":
            set_session_phase(session, "failed")
            update_deploy_state(
                session,
                pending_tool_id=None,
                pending_tool_name=None,
                pending_input_kind=None,
                last_tool_state="error",
                last_error=str(exc),
                last_message=str(exc),
            )
        elif session.agent_type == "plan":
            set_session_phase(session, "planning")
            update_plan_state(session, status="clarifying")
        await queue.put(_session_state_event())
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
        if session.agent_type == "deploy":
            reset_phase_for_new_turn(session)
            update_deploy_state(
                session,
                pending_tool_id=None,
                pending_tool_name=None,
                pending_input_kind=None,
                last_message="用户已停止当前任务。",
            )
        elif session.agent_type == "plan":
            reset_phase_for_new_turn(session)
        set_session_generating(session, False)
        await queue.put(_session_state_event())
        await queue.put(None)
        return

    if session.agent_type == "deploy" and not session.pending_connect_requests and session.phase != "failed":
        set_session_phase(session, "completed")
        update_deploy_state(
            session,
            pending_tool_id=None,
            pending_tool_name=None,
            pending_input_kind=None,
        )
    if session.agent_type == "plan" and not session.pending_user_input_requests and session.plan_state.get("draft"):
        set_session_phase(session, "plan_ready")
        update_plan_state(session, status="draft_ready")
    await queue.put(_session_state_event())
    final_output = response.final_output
    has_final_output = bool(final_output)
    if has_final_output:
        replace_assistant_text_part(session, assistant_id, final_output)
    remaining_output = final_output
    should_reset_before_replay = not assistant_stream_started
    if assistant_stream_started:
        if not has_final_output:
            remaining_output = ""
            should_reset_before_replay = False
        elif final_output.startswith(streamed_assistant_text):
            remaining_output = final_output[len(streamed_assistant_text) :]
        else:
            should_reset_before_replay = True
            remaining_output = final_output

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

    auto_compression_response = await asyncio.to_thread(
        auto_compress_session_context_if_needed,
        session,
    )
    if auto_compression_response is not None:
        await queue.put(_session_state_event())

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
    await queue.put(
        {
            "type": "data-session-state",
            "payload": {
                "assistant_id": assistant_id,
                "data": {
                    "agentType": session.agent_type,
                    "phase": session.phase,
                    "deployState": session.deploy_state,
                    "planState": session.plan_state,
                },
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


def normalize_workspace(raw_workspace: str | None) -> str:
    return normalize_workspace_impl(raw_workspace, DEFAULT_WORKSPACE)


def list_workspace_options() -> list[dict[str, str]]:
    return list_workspace_options_impl(DEFAULT_WORKSPACE)


def _session_has_pending_context_interaction(session: UISession) -> bool:
    return any(
        (
            session.pending_user_input_requests,
            session.pending_connect_requests,
            session.pending_delete_confirmations,
            session.pending_commit_confirmations,
            session.pending_tag_confirmations,
        )
    )


def _clone_deploy_connection_manager(session: UISession) -> DeployConnectionManager:
    manager = DeployConnectionManager(workspace=resolve_workspace_path(session.workspace))
    for connection in session.deploy_connection_manager.export_state().values():
        if isinstance(connection, dict):
            manager.register_connection(deepcopy(connection))
    return manager


def _rebuild_chat_session_for_existing_history(
    *,
    session_id: str,
    workspace: str,
    env_file: str | None,
    agent_type: str,
    reasoning_effort: str | None,
    history_messages: list[dict[str, Any]],
    history_tools: list[dict[str, Any]],
    deploy_connection_manager: DeployConnectionManager,
    phase: str,
    selected_file_path: str | None,
    open_files: list[str],
    terminal_output: str,
    preview_url: str,
    code_changes: list[dict[str, Any]],
    thoughts: list[str],
    plan_steps: list[dict[str, str]],
    plan_state: dict[str, Any],
    route_state: dict[str, Any],
    deploy_state: dict[str, Any],
    startup_error: str | None,
    mode: str,
) -> UISession:
    chat_session, model_name, build_error, env_file_used, resolved_reasoning_effort = build_chat_session(
        workspace,
        env_file,
        agent_type=agent_type,
        reasoning_effort=reasoning_effort,
    )
    interactive_command_session = InteractiveCommandSession(
        workspace=resolve_workspace_path(workspace)
    )
    session = UISession(
        session_id=session_id,
        model=model_name if chat_session is not None else "Demo",
        reasoning_effort=resolved_reasoning_effort if chat_session is not None else reasoning_effort,
        workspace=workspace,
        mode="agent" if chat_session is not None else mode,
        agent_type=agent_type,
        phase=phase,
        route_state=deepcopy(route_state),
        is_generating=False,
        startup_error=startup_error if chat_session is not None else (build_error or startup_error),
        env_file=env_file_used or env_file,
        selected_file_path=selected_file_path,
        open_files=deepcopy(open_files),
        terminal_output=terminal_output,
        preview_url=preview_url or DEFAULT_BROWSER_PREVIEW_URL,
        terminal_runtime=TerminalRuntime(workspace=workspace),
        interactive_command_session=interactive_command_session,
        chat_session=chat_session,
        history_messages=deepcopy(history_messages),
        history_tools=deepcopy(history_tools),
        code_changes=deepcopy(code_changes),
        thoughts=deepcopy(thoughts),
        plan_steps=deepcopy(plan_steps),
        plan_state=deepcopy(plan_state),
        deploy_connection_manager=deploy_connection_manager,
        deploy_state=deepcopy(deploy_state),
    )
    if session.chat_session is not None:
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
    if session.chat_session is not None and isinstance(session.chat_session.agent, Agent):
        attach_agent_runtime_metadata(
            session.chat_session.agent,
            session_id=session.session_id,
            interactive_command_session=interactive_command_session,
            cancel_event=session.cancel_event,
            deploy_connection_manager=deploy_connection_manager,
        )
        sync_session_runtime_state_for_agent(session)
    return session


def fork_session_from_current(session: UISession) -> UISession:
    new_session_id = uuid.uuid4().hex
    deploy_connection_manager = _clone_deploy_connection_manager(session)
    forked_session = _rebuild_chat_session_for_existing_history(
        session_id=new_session_id,
        workspace=session.workspace,
        env_file=session.env_file,
        agent_type=session.agent_type,
        reasoning_effort=session.reasoning_effort,
        history_messages=session.history_messages,
        history_tools=session.history_tools,
        deploy_connection_manager=deploy_connection_manager,
        phase=session.phase,
        selected_file_path=session.selected_file_path,
        open_files=session.open_files,
        terminal_output=session.terminal_output,
        preview_url=session.preview_url,
        code_changes=session.code_changes,
        thoughts=session.thoughts,
        plan_steps=session.plan_steps,
        plan_state=session.plan_state,
        route_state=session.route_state,
        deploy_state=session.deploy_state,
        startup_error=session.startup_error,
        mode=session.mode,
    )
    forked_session.created_at = int(time.time() * 1000)
    forked_session.updated_at = forked_session.created_at
    refresh_session_runtime_state(forked_session)
    sync_session_runtime_state_for_agent(forked_session)
    _sessions[forked_session.session_id] = forked_session
    persist_session_state(forked_session)
    return forked_session


def _collect_tool_call_ids_from_messages(messages: list[dict[str, Any]]) -> set[str]:
    tool_ids: set[str] = set()
    for message in messages:
        raw_tool_calls = message.get("toolCalls")
        if isinstance(raw_tool_calls, list):
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue
                tool_id = str(raw_tool_call.get("id") or "").strip()
                if tool_id:
                    tool_ids.add(tool_id)
        raw_parts = message.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if not isinstance(part, dict):
                continue
            raw_tool_call = part.get("toolCall")
            if not isinstance(raw_tool_call, dict):
                continue
            tool_id = str(raw_tool_call.get("id") or "").strip()
            if tool_id:
                tool_ids.add(tool_id)
    return tool_ids


def _collect_assistant_message_ids(messages: list[dict[str, Any]]) -> set[str]:
    return {
        str(message.get("id") or "").strip()
        for message in messages
        if str(message.get("role", "")) == "assistant" and str(message.get("id") or "").strip()
    }


def _rebuild_thoughts_from_history_messages(messages: list[dict[str, Any]]) -> list[str]:
    thoughts: list[str] = []
    for message in messages:
        if str(message.get("role", "")) != "assistant":
            continue
        thought_text = extract_message_thought_text(message)
        if thought_text:
            thoughts.append(thought_text)
    return thoughts


def _filter_code_changes_for_restored_history(
    code_changes: list[dict[str, Any]],
    retained_assistant_ids: set[str],
    removed_assistant_ids: set[str],
    retained_tool_ids: set[str],
    removed_tool_ids: set[str],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for change in code_changes:
        assistant_id = str(change.get("assistantId") or "").strip()
        tool_call_id = str(change.get("toolCallId") or "").strip()
        if assistant_id and assistant_id in removed_assistant_ids:
            continue
        if tool_call_id and tool_call_id in removed_tool_ids:
            continue
        if assistant_id and retained_assistant_ids and assistant_id not in retained_assistant_ids and assistant_id in removed_assistant_ids:
            continue
        if tool_call_id and retained_tool_ids and tool_call_id not in retained_tool_ids and tool_call_id in removed_tool_ids:
            continue
        filtered.append(deepcopy(change))
    return filtered


def restore_session_to_message(session: UISession, message_id: str) -> CreateSessionResponse:
    target_message_id = str(message_id or "").strip()
    if not target_message_id:
        raise HTTPException(status_code=400, detail="messageId 不能为空")

    target_index = next(
        (
            index
            for index, message in enumerate(session.history_messages)
            if str(message.get("id") or "").strip() == target_message_id
        ),
        -1,
    )
    if target_index < 0:
        raise HTTPException(status_code=404, detail="未找到对应的消息")

    target_message = session.history_messages[target_index]
    if str(target_message.get("role", "")) != "assistant":
        raise HTTPException(status_code=400, detail="只能还原到助手消息")

    kept_messages = deepcopy(session.history_messages[: target_index + 1])
    removed_messages = session.history_messages[target_index + 1 :]
    retained_tool_ids = _collect_tool_call_ids_from_messages(kept_messages)
    removed_tool_ids = _collect_tool_call_ids_from_messages(removed_messages)
    retained_assistant_ids = _collect_assistant_message_ids(kept_messages)
    removed_assistant_ids = _collect_assistant_message_ids(removed_messages)
    kept_tools = [
        deepcopy(tool)
        for tool in session.history_tools
        if str(tool.get("id") or "").strip() in retained_tool_ids
    ]
    kept_thoughts = _rebuild_thoughts_from_history_messages(kept_messages)
    kept_code_changes = _filter_code_changes_for_restored_history(
        session.code_changes,
        retained_assistant_ids=retained_assistant_ids,
        removed_assistant_ids=removed_assistant_ids,
        retained_tool_ids=retained_tool_ids,
        removed_tool_ids=removed_tool_ids,
    )

    session.history_messages = kept_messages
    session.history_tools = kept_tools
    session.thoughts = kept_thoughts
    invalidate_session_context_usage(session)
    session.code_changes = kept_code_changes
    session.pending_user_input_requests.clear()
    session.pending_connect_requests.clear()
    session.pending_delete_confirmations.clear()
    session.pending_commit_confirmations.clear()
    session.pending_tag_confirmations.clear()
    set_session_phase(session, "idle")
    if session.chat_session is not None:
        session.chat_session.clear()
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        sync_session_runtime_state_for_agent(session)
    session.touch()
    return session.snapshot()


def _clamp_non_negative_int(value: int | None, default: int) -> int:
    try:
        normalized = int(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return max(0, normalized)


def _clamp_unit_float(value: float | None, default: float) -> float:
    try:
        normalized = float(value if value is not None else default)
    except (TypeError, ValueError):
        return default
    return min(max(normalized, 0.0), 1.0)


def _slice_items_for_summary(items: list[Any], head_count: int, tail_count: int) -> list[Any]:
    if len(items) <= head_count + tail_count:
        return list(items)
    head = list(items[:head_count])
    tail = list(items[-tail_count:]) if tail_count > 0 else []
    return head + tail


def _compact_unknown(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    return compact_text(text, limit)


def _slice_context_for_compression(
    session: UISession,
    request: SessionContextCompressionRequest,
) -> ContextCompressionSlices:
    preserve_recent_messages = _clamp_non_negative_int(
        request.preserveRecentMessages,
        DEFAULT_CONTEXT_COMPRESSION_RECENT_MESSAGES,
    )
    preserve_recent_tools = _clamp_non_negative_int(
        request.preserveRecentTools,
        DEFAULT_CONTEXT_COMPRESSION_RECENT_TOOLS,
    )
    preserve_recent_thoughts = _clamp_non_negative_int(
        request.preserveRecentThoughts,
        DEFAULT_CONTEXT_COMPRESSION_RECENT_THOUGHTS,
    )

    if preserve_recent_messages > 0:
        archived_messages = list(session.history_messages[:-preserve_recent_messages])
        preserved_messages = list(session.history_messages[-preserve_recent_messages:])
    else:
        archived_messages = list(session.history_messages)
        preserved_messages = []

    if preserve_recent_tools > 0:
        archived_tools = list(session.history_tools[:-preserve_recent_tools])
        preserved_tools = list(session.history_tools[-preserve_recent_tools:])
    else:
        archived_tools = list(session.history_tools)
        preserved_tools = []

    if preserve_recent_thoughts > 0:
        archived_thoughts = list(session.thoughts[:-preserve_recent_thoughts])
        preserved_thoughts = list(session.thoughts[-preserve_recent_thoughts:])
    else:
        archived_thoughts = list(session.thoughts)
        preserved_thoughts = []

    return ContextCompressionSlices(
        archived_messages=archived_messages,
        preserved_messages=preserved_messages,
        archived_tools=archived_tools,
        preserved_tools=preserved_tools,
        archived_thoughts=archived_thoughts,
        preserved_thoughts=preserved_thoughts,
    )


def _format_messages_for_context_compression(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    sampled_messages = _slice_items_for_summary(
        messages,
        head_count=4,
        tail_count=max(MAX_CONTEXT_COMPRESSION_SOURCE_MESSAGES - 4, 0),
    )
    for message in sampled_messages:
        role = "用户" if str(message.get("role", "")) == "user" else "助手"
        content = compact_text(str(message.get("content", "")), 220)
        if content:
            lines.append(f"- {role}: {content}")
        thought_text = compact_text(str(message.get("thoughts", "")), 160)
        if thought_text:
            lines.append(f"  思考: {thought_text}")
    return "\n".join(lines) or "- 无"


def _format_tools_for_context_compression(tools: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    sampled_tools = _slice_items_for_summary(
        tools,
        head_count=2,
        tail_count=max(MAX_CONTEXT_COMPRESSION_SOURCE_TOOLS - 2, 0),
    )
    for tool in sampled_tools:
        name = str(tool.get("name") or "unknown")
        state = str(tool.get("state") or "unknown")
        arguments = _compact_unknown(tool.get("arguments"), 160)
        output = _compact_unknown(tool.get("output"), 180)
        segments = [f"- {name} [{state}]"]
        if arguments:
            segments.append(f"args={arguments}")
        if output:
            segments.append(f"output={output}")
        lines.append(" ".join(segments))
    return "\n".join(lines) or "- 无"


def _format_thoughts_for_context_compression(thoughts: list[str]) -> str:
    lines = [
        f"- {compact_text(thought, 220)}"
        for thought in _slice_items_for_summary(
            thoughts,
            head_count=2,
            tail_count=max(MAX_CONTEXT_COMPRESSION_SOURCE_THOUGHTS - 2, 0),
        )
        if compact_text(thought, 220)
    ]
    return "\n".join(lines) or "- 无"


def _format_code_changes_for_context_compression(code_changes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for change in code_changes[-MAX_CONTEXT_COMPRESSION_SOURCE_CODE_CHANGES:]:
        path = str(change.get("path") or "")
        action = str(change.get("action") or "modified")
        summary = compact_text(str(change.get("summary") or ""), 160)
        lines.append(f"- {action} {path}: {summary or '无摘要'}")
    return "\n".join(lines) or "- 无"


def _format_plan_steps_for_context_compression(plan_steps: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for step in plan_steps:
        title = str(step.get("title") or "").strip()
        if not title:
            continue
        status = str(step.get("status") or "pending")
        description = compact_text(str(step.get("description") or ""), 120)
        if description:
            lines.append(f"- [{status}] {title}: {description}")
        else:
            lines.append(f"- [{status}] {title}")
    return "\n".join(lines) or "- 无"


def build_context_compression_source(
    session: UISession,
    slices: ContextCompressionSlices,
    instruction: str | None = None,
) -> str:
    first_user_message = next(
        (
            compact_text(str(message.get("content", "")), 240)
            for message in session.history_messages
            if str(message.get("role", "")) == "user" and str(message.get("content", "")).strip()
        ),
        "无",
    )
    sections = [
        f"工作区: {session.workspace}",
        f"会话模式: {session.agent_type} / {session.phase}",
        f"当前文件: {session.selected_file_path or '无'}",
        f"打开标签: {', '.join(session.open_files[-6:]) or '无'}",
        f"初始用户目标: {first_user_message}",
        f"当前会话预览: {session.summary_preview()}",
        "计划步骤:\n" + _format_plan_steps_for_context_compression(session.plan_steps),
        "待压缩消息:\n" + _format_messages_for_context_compression(slices.archived_messages),
        "待压缩工具调用:\n" + _format_tools_for_context_compression(slices.archived_tools),
        "待压缩思考:\n" + _format_thoughts_for_context_compression(slices.archived_thoughts),
        "最近代码变更:\n" + _format_code_changes_for_context_compression(session.code_changes),
    ]
    if instruction and instruction.strip():
        sections.append(f"额外要求: {instruction.strip()}")
    return "\n\n".join(section for section in sections if section.strip())


def _clean_context_compression_summary(summary: str) -> str:
    cleaned = summary.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.replace(CONTEXT_COMPRESSION_SUMMARY_PREFIX, "").strip()
    cleaned_lines = [line.rstrip() for line in cleaned.splitlines() if line.strip()]
    cleaned = "\n".join(cleaned_lines).strip()
    if len(cleaned) > 2_400:
        cleaned = f"{cleaned[:2400].rstrip()}..."
    return cleaned


def _build_context_compression_fallback_summary(
    session: UISession,
    slices: ContextCompressionSlices,
) -> str:
    goal = next(
        (
            compact_text(str(message.get("content", "")), 180)
            for message in session.history_messages
            if str(message.get("role", "")) == "user" and str(message.get("content", "")).strip()
        ),
        session.summary_title(),
    )
    completed_items = [
        f"- {str(change.get('action') or 'modified')} {str(change.get('path') or '')}: "
        f"{compact_text(str(change.get('summary') or ''), 120) or '已修改'}"
        for change in session.code_changes[-4:]
    ]
    if not completed_items:
        completed_items = [
            f"- {str(tool.get('name') or 'tool')} [{str(tool.get('state') or 'unknown')}]"
            for tool in slices.archived_tools[-3:]
        ] or ["- 暂无明确已完成事项"]
    pending_items = [
        f"- {str(step.get('title') or '').strip()}"
        for step in session.plan_steps
        if str(step.get("status") or "pending") != "completed" and str(step.get("title") or "").strip()
    ] or ["- 保持当前最近对话继续推进"]
    context_items = [
        f"- 工作区: {session.workspace}",
        f"- 当前文件: {session.selected_file_path or '无'}",
        f"- 打开标签: {', '.join(session.open_files[-4:]) or '无'}",
    ]
    if session.history_tools:
        latest_tool = session.history_tools[-1]
        context_items.append(
            f"- 最近工具: {str(latest_tool.get('name') or 'tool')} [{str(latest_tool.get('state') or 'unknown')}]"
        )
    return "\n".join(
        [
            "## 目标",
            goal,
            "",
            "## 已完成",
            *completed_items,
            "",
            "## 待继续",
            *pending_items,
            "",
            "## 关键上下文",
            *context_items,
        ]
    ).strip()


def _summarize_context_with_model(
    session: UISession,
    source_text: str,
    instruction: str | None = None,
) -> str:
    model_ref = session.env_file
    if not model_ref:
        try:
            model_ref = resolve_model_option(session.model, None)["envFile"]
        except HTTPException:
            model_ref = None
    config, _normalized_model_ref = build_agent_config(ROOT, model_ref)
    if session.reasoning_effort:
        config.reasoning_effort = normalize_reasoning_effort(session.reasoning_effort)
    client = OpenAICompatibleClient(config)
    user_prompt = "\n\n".join(
        part
        for part in [
            "请把下面这段 AI 编码会话的较早上下文压缩成一份后续可继续工作的摘要。",
            "要求：1. 保留用户目标、约束、已完成改动、未完成事项、关键文件和风险；"
            "2. 不要编造；3. 使用中文；4. 用简洁小标题组织；5. 不要输出代码块。",
            f"额外要求：{instruction.strip()}" if instruction and instruction.strip() else "",
            source_text,
        ]
        if part
    )
    summary = client.chat_messages(
        [
            {"role": "system", "content": "你是一个负责为编码代理压缩历史上下文的摘要助手。"},
            {"role": "user", "content": user_prompt},
        ]
    )
    add_cumulative_session_token_usage(session, client.last_usage)
    return _clean_context_compression_summary(summary)


def _build_context_compression_message(summary: str) -> dict[str, Any]:
    cleaned_summary = _clean_context_compression_summary(summary)
    content = (
        cleaned_summary
        if cleaned_summary.startswith(CONTEXT_COMPRESSION_SUMMARY_PREFIX)
        else f"{CONTEXT_COMPRESSION_SUMMARY_PREFIX}\n{cleaned_summary}"
    )
    return {
        "id": uuid.uuid4().hex,
        "role": "assistant",
        "content": content,
        "parts": [{"type": "text", "text": content}],
    }


def _estimate_context_tokens_from_parts(
    history_messages: list[dict[str, Any]],
    thoughts: list[str],
    history_tools: list[dict[str, Any]],
    workspace: str,
) -> int:
    total_chars = 0
    for message in history_messages:
        total_chars += len(str(message.get("content", "")))
    for thought in thoughts:
        total_chars += len(thought)
    for tool in history_tools:
        total_chars += len(str(tool.get("name", "")))
        total_chars += len(json.dumps(tool.get("arguments", {}), ensure_ascii=False))
        output = tool.get("output")
        if output is not None:
            if isinstance(output, str):
                total_chars += len(output)
            else:
                try:
                    total_chars += len(json.dumps(output, ensure_ascii=False))
                except TypeError:
                    total_chars += len(str(output))
    total_chars += len(workspace)
    return max(1, total_chars // 4)


def compress_session_context(
    session: UISession,
    request: SessionContextCompressionRequest,
    summarizer: Callable[[UISession, str, str | None], str] | None = None,
) -> SessionContextCompressionResponse:
    slices = _slice_context_for_compression(session, request)
    original_estimated_tokens = estimate_session_context_tokens(session)
    max_tokens = max(session.max_context_tokens or infer_model_context_limit(session.model), 1)
    usage_threshold = _clamp_unit_float(
        request.usageThreshold,
        DEFAULT_CONTEXT_COMPRESSION_USAGE_THRESHOLD,
    )
    usage_ratio = min(max(original_estimated_tokens / max_tokens, 0.0), 1.0)
    source_text = build_context_compression_source(session, slices, request.instruction)
    has_archived_context = any(
        (
            slices.archived_messages,
            slices.archived_tools,
            slices.archived_thoughts,
        )
    )
    if usage_ratio < usage_threshold:
        return SessionContextCompressionResponse(
            sessionId=session.session_id,
            mode=request.mode,
            applied=False,
            summary="",
            usageRatio=usage_ratio,
            usageThreshold=usage_threshold,
            sourceMessageCount=len(slices.archived_messages),
            sourceToolCount=len(slices.archived_tools),
            sourceThoughtCount=len(slices.archived_thoughts),
            preservedMessageCount=len(slices.preserved_messages),
            preservedToolCount=len(slices.preserved_tools),
            preservedThoughtCount=len(slices.preserved_thoughts),
            originalEstimatedTokens=original_estimated_tokens,
            maxTokens=max_tokens,
            compressedEstimatedTokens=original_estimated_tokens,
            savedEstimatedTokens=0,
            usedFallback=False,
            skippedReason="usage_below_threshold",
            updatedContext=None,
        )
    if not has_archived_context:
        return SessionContextCompressionResponse(
            sessionId=session.session_id,
            mode=request.mode,
            applied=False,
            summary="",
            usageRatio=usage_ratio,
            usageThreshold=usage_threshold,
            sourceMessageCount=0,
            sourceToolCount=0,
            sourceThoughtCount=0,
            preservedMessageCount=len(slices.preserved_messages),
            preservedToolCount=len(slices.preserved_tools),
            preservedThoughtCount=len(slices.preserved_thoughts),
            originalEstimatedTokens=original_estimated_tokens,
            maxTokens=max_tokens,
            compressedEstimatedTokens=original_estimated_tokens,
            savedEstimatedTokens=0,
            usedFallback=False,
            skippedReason="no_archived_context",
            updatedContext=None,
        )

    used_fallback = False
    summary = ""
    try:
        summary = (
            summarizer(session, source_text, request.instruction)
            if summarizer is not None
            else _summarize_context_with_model(session, source_text, request.instruction)
        )
    except Exception:
        used_fallback = True
        summary = ""
    if not summary:
        used_fallback = True
        summary = _build_context_compression_fallback_summary(session, slices)
    cleaned_summary = _clean_context_compression_summary(summary) or _build_context_compression_fallback_summary(session, slices)

    summary_message = _build_context_compression_message(cleaned_summary)
    projected_history_messages = (
        [summary_message, *slices.preserved_messages]
    )
    projected_history_tools = slices.preserved_tools
    projected_thoughts = slices.preserved_thoughts
    compressed_estimated_tokens = _estimate_context_tokens_from_parts(
        projected_history_messages,
        projected_thoughts,
        projected_history_tools,
        session.workspace,
    )
    saved_estimated_tokens = max(original_estimated_tokens - compressed_estimated_tokens, 0)

    applied = request.mode == "apply"
    updated_context: SessionContextResponse | None = None
    if applied:
        session.history_messages = projected_history_messages
        session.history_tools = projected_history_tools
        session.thoughts = projected_thoughts
        invalidate_session_context_usage(session)
        if session.chat_session is not None:
            session.chat_session.clear()
            seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
            sync_session_runtime_state_for_agent(session)
        session.touch()
        updated_context = session.context_snapshot()

    return SessionContextCompressionResponse(
        sessionId=session.session_id,
        mode=request.mode,
        applied=applied,
        summary=cleaned_summary,
        usageRatio=usage_ratio,
        usageThreshold=usage_threshold,
        sourceMessageCount=len(slices.archived_messages),
        sourceToolCount=len(slices.archived_tools),
        sourceThoughtCount=len(slices.archived_thoughts),
        preservedMessageCount=len(slices.preserved_messages),
        preservedToolCount=len(slices.preserved_tools),
        preservedThoughtCount=len(slices.preserved_thoughts),
        originalEstimatedTokens=original_estimated_tokens,
        maxTokens=max_tokens,
        compressedEstimatedTokens=compressed_estimated_tokens,
        savedEstimatedTokens=saved_estimated_tokens,
        usedFallback=used_fallback,
        skippedReason=None,
        updatedContext=updated_context,
    )


def auto_compress_session_context_if_needed(
    session: UISession,
) -> SessionContextCompressionResponse | None:
    response = compress_session_context(
        session,
        SessionContextCompressionRequest(
            mode="apply",
            usageThreshold=DEFAULT_CONTEXT_COMPRESSION_USAGE_THRESHOLD,
        ),
    )
    return response if response.applied else None


def estimate_session_tokens(session: UISession) -> int:
    return _estimate_context_tokens_from_parts(
        session.history_messages,
        session.thoughts,
        session.history_tools,
        session.workspace,
    )


def estimate_session_context_tokens(session: UISession) -> int:
    token_usage = normalize_session_token_usage(session.token_usage)
    if token_usage["inputTokens"] > 0:
        return token_usage["inputTokens"]
    return estimate_session_tokens(session)


def invalidate_session_context_usage(session: UISession) -> None:
    session.token_usage = _empty_session_token_usage()


def add_cumulative_session_token_usage(session: UISession, usage: dict[str, int] | None) -> None:
    normalized_usage = normalize_session_token_usage(usage)
    if not any(normalized_usage.values()):
        return

    cumulative_usage = normalize_session_token_usage(session.cumulative_token_usage)
    for key, value in normalized_usage.items():
        cumulative_usage[key] = max(cumulative_usage.get(key, 0) + value, 0)
    if cumulative_usage["totalTokens"] == 0:
        cumulative_usage["totalTokens"] = (
            cumulative_usage["inputTokens"] + cumulative_usage["outputTokens"]
        )
    session.cumulative_token_usage = cumulative_usage


def merge_session_token_usage(session: UISession, usage: dict[str, int] | None) -> None:
    normalized_usage = normalize_session_token_usage(usage)
    if not any(normalized_usage.values()):
        return

    session.token_usage = normalized_usage
    add_cumulative_session_token_usage(session, normalized_usage)


def build_session_state_payload(session: UISession) -> dict[str, Any]:
    return {
        "agentType": session.agent_type,
        "phase": session.phase,
        "routeState": session.route_state,
        "deployState": session.deploy_state,
        "planState": session.plan_state,
        "messageCount": len(session.history_messages),
        "toolCallCount": len(session.history_tools),
        "thoughtCount": len(session.thoughts),
        "estimatedTokens": estimate_session_context_tokens(session),
        "maxTokens": max(session.max_context_tokens or infer_model_context_limit(session.model), 1),
        "usage": normalize_session_token_usage(session.token_usage),
        "cumulativeUsage": normalize_session_token_usage(session.cumulative_token_usage),
        "codeChangeCount": len(session.code_changes),
        "recentCodeChanges": session.code_changes[-8:],
    }


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


def resolve_workspace_target(session_id: str, path: str) -> tuple[UISession, Path, str]:
    session = require_session(session_id)
    resolved_path = normalize_relative_path(path, session.workspace)
    target = Path(resolved_path).expanduser().resolve()
    workspace_root = resolve_workspace_path(session.workspace)
    if workspace_root != target and workspace_root not in target.parents:
        raise HTTPException(status_code=403, detail="路径不在工作区内")
    return session, target, resolved_path


def launch_editor_process(*, editor: str, target: Path) -> list[str]:
    normalized_editor = editor.strip()
    if normalized_editor not in SUPPORTED_EDITOR_COMMANDS:
        raise HTTPException(status_code=400, detail=f"不支持的编辑器命令：{normalized_editor}")

    executable = shutil.which(normalized_editor)
    if not executable:
        raise HTTPException(status_code=404, detail=f"未找到编辑器命令：{normalized_editor}")

    command = [executable, str(target)]
    if normalized_editor == "devenv":
        command = [executable, "/Edit", str(target)]

    popen_kwargs: dict[str, Any] = {
        "cwd": str(target.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(command, **popen_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"未找到编辑器命令：{normalized_editor}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"启动编辑器失败：{exc}") from exc

    return command


def relative_workspace_path(path: str | Path, workspace: str) -> str:
    workspace_root = resolve_workspace_path(workspace)
    target = Path(path).expanduser().resolve()
    try:
        return target.relative_to(workspace_root).as_posix()
    except ValueError:
        return str(target)


def count_text_lines(text: str | None) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def extract_apply_patch_paths(patch_text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("*** Update File: "):
            continue
        path = line.removeprefix("*** Update File: ").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def capture_code_change_before_snapshots(
    session: UISession,
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
) -> dict[str, str]:
    raw_targets: list[str] = []
    if tool_name in {"replace_file", "delete_file"}:
        filename = str(tool_arguments.get("filename") or "").strip()
        if filename:
            raw_targets.append(filename)
    elif tool_name == "apply_patch":
        filename = str(tool_arguments.get("filename") or "").strip()
        if filename:
            raw_targets.append(filename)

    snapshots: dict[str, str] = {}
    for raw_target in raw_targets:
        try:
            target = Path(normalize_relative_path(raw_target, session.workspace))
        except HTTPException:
            continue
        relative_path = relative_workspace_path(target, session.workspace)
        snapshots[relative_path] = read_text_file(str(target), session.workspace)
    return snapshots


def build_code_diff_preview(relative_path: str, before_text: str, after_text: str) -> tuple[str, int, int]:
    diff_lines = list(
        difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    preview_lines = diff_lines[:MAX_CODE_CHANGE_DIFF_LINES]
    if len(diff_lines) > MAX_CODE_CHANGE_DIFF_LINES:
        preview_lines.append(f"... truncated {len(diff_lines) - MAX_CODE_CHANGE_DIFF_LINES} diff lines")
    return "\n".join(preview_lines), added, deleted


def record_code_change(
    session: UISession,
    *,
    action: str,
    path: str | Path,
    before_text: str = "",
    after_text: str = "",
    source: str = "agent",
    tool_call_id: str | None = None,
    assistant_id: str | None = None,
    turn_index: int | None = None,
    step_index: int | None = None,
    summary: str | None = None,
) -> dict[str, Any] | None:
    if action == "modified" and before_text == after_text:
        return None

    absolute_path = Path(path).expanduser().resolve()
    relative_path = relative_workspace_path(absolute_path, session.workspace)
    diff_preview, added, deleted = build_code_diff_preview(relative_path, before_text, after_text)
    if action == "added":
        added = count_text_lines(after_text)
        deleted = 0
    elif action == "deleted":
        added = 0
        deleted = count_text_lines(before_text)

    if summary is None:
        action_label = {"added": "新增", "modified": "修改", "deleted": "删除"}.get(action, "变更")
        summary = f"{action_label} {relative_path}"

    record = {
        "id": uuid.uuid4().hex,
        "action": action,
        "path": relative_path,
        "absolutePath": str(absolute_path),
        "source": source,
        "toolCallId": tool_call_id,
        "assistantId": assistant_id,
        "turnIndex": turn_index,
        "stepIndex": step_index,
        "timestamp": int(time.time() * 1000),
        "linesAdded": added,
        "linesDeleted": deleted,
        "summary": summary,
        "diffPreview": diff_preview,
    }
    session.code_changes = [*session.code_changes, record][-MAX_CODE_CHANGE_RECORDS:]
    return record


def current_agent_turn_index(session: UISession) -> int | None:
    state = getattr(session.chat_session, "state", None)
    data = getattr(state, "data", None)
    if not isinstance(data, dict):
        return None
    try:
        return int(data.get("turn_index"))
    except (TypeError, ValueError):
        return None


def code_change_records_from_tool_result(
    session: UISession,
    *,
    tool_name: str,
    tool_arguments: dict[str, Any],
    output: Any,
    tool_call_id: str,
    assistant_id: str,
    step_index: int | None,
    before_snapshots: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    before_snapshots = before_snapshots or {}
    if tool_name == "write_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        after_text = read_text_file(str(target), session.workspace)
        record = record_code_change(
            session,
            action="added",
            path=target,
            before_text="",
            after_text=after_text,
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    if tool_name == "replace_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        relative_path = relative_workspace_path(target, session.workspace)
        before_text = before_snapshots.get(relative_path, str(tool_arguments.get("old_content") or ""))
        after_text = read_text_file(str(target), session.workspace)
        record = record_code_change(
            session,
            action="modified",
            path=target,
            before_text=before_text,
            after_text=after_text,
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    if tool_name == "apply_patch" and isinstance(output, dict):
        files = output.get("files")
        if not isinstance(files, list) or not files:
            return []
        records: list[dict[str, Any]] = []
        for raw_file in files:
            target = Path(normalize_relative_path(str(raw_file), session.workspace))
            relative_path = relative_workspace_path(target, session.workspace)
            after_text = read_text_file(str(target), session.workspace)
            record = record_code_change(
                session,
                action="modified",
                path=target,
                before_text=before_snapshots.get(relative_path, ""),
                after_text=after_text,
                source="agent",
                tool_call_id=tool_call_id,
                assistant_id=assistant_id,
                turn_index=current_agent_turn_index(session),
                step_index=step_index,
                summary=f"应用补丁 {relative_path}",
            )
            if record is not None:
                records.append(record)
        return records

    if tool_name == "delete_file":
        filename = str(tool_arguments.get("filename") or "").strip()
        if not filename:
            return []
        target = Path(normalize_relative_path(filename, session.workspace))
        relative_path = relative_workspace_path(target, session.workspace)
        record = record_code_change(
            session,
            action="deleted",
            path=target,
            before_text=before_snapshots.get(relative_path, ""),
            after_text="",
            source="agent",
            tool_call_id=tool_call_id,
            assistant_id=assistant_id,
            turn_index=current_agent_turn_index(session),
            step_index=step_index,
        )
        return [record] if record is not None else []

    return []


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

    uvicorn.run(app, host="0.0.0.0", port=3001)
