from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple

from agent import ChatSession
from coding_agent import InteractiveCommandSession
from deploy_agent import DeployConnectionManager

from fastapi_app.agent_router import normalize_route_state
from fastapi_app.app_config import DEFAULT_BROWSER_PREVIEW_URL, DEFAULT_OPEN_FILES, DEFAULT_SELECTED_FILE, is_desktop_mode
from fastapi_app.api_models import (
    CreateSessionResponse,
    SessionContextMessage,
    SessionContextResponse,
    SessionContextTool,
    SessionHistoryItem,
    SessionTokenUsage,
    TerminalSnapshotResponse,
)
from fastapi_app.runtime.context import (
    compact_text,
    estimate_session_context_tokens,
    infer_model_context_limit,
    normalize_session_token_usage,
)
from fastapi_app.runtime.terminal import TerminalRuntime
from fastapi_app.runtime.worktree import normalize_execution_mode
from fastapi_app.session.agent_runtime import (
    normalize_deploy_state,
    normalize_plan_state,
    normalize_session_phase,
    refresh_session_runtime_state,
)
from fastapi_app.session_history import is_subagent_record
from fastapi_app.skills import list_available_skill_summaries
from fastapi_app.workspace_utils import (
    build_directory_tree_node,
    build_file_tree,
    build_file_tree_root,
    read_text_file,
    normalize_relative_path,
    resolve_workspace_path,
)


class WorkspaceTreeSubscriber(NamedTuple):
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any] | None]


@dataclass(frozen=True)
class UISessionBindings:
    sync_session_runtime_state_for_agent: Callable[[Any], None]
    persist_session_state: Callable[[Any], None]
    resolve_model_reference_id: Callable[[str | None, str | None], str | None]
    list_workspace_options: Callable[[], list[dict[str, str]]]


@dataclass
class UISession:
    session_id: str
    model: str
    workspace: str
    bindings: UISessionBindings = field(repr=False)
    reasoning_effort: str | None = None
    mode: str = "demo"
    execution_mode: str = "local"
    base_workspace: str | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None
    agent_type: str = "coding"
    phase: str = "idle"
    route_state: dict[str, Any] = field(default_factory=dict)
    startup_error: str | None = None
    env_file: str | None = None
    selected_file_path: str | None = DEFAULT_SELECTED_FILE
    open_files: list[str] = field(default_factory=lambda: list(DEFAULT_OPEN_FILES))
    terminal_output: str = ""
    preview_url: str = DEFAULT_BROWSER_PREVIEW_URL
    terminal_runtimes: dict[str, TerminalRuntime] = field(default_factory=dict, init=False, repr=False)
    default_terminal_id: str | None = field(default=None, init=False, repr=False)
    interactive_command_session: InteractiveCommandSession | None = field(default=None, repr=False)
    chat_session: ChatSession | None = None
    is_generating: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    cached_file_tree: list[dict[str, Any]] = field(default_factory=list, repr=False)
    file_tree_loaded: bool = field(default=False, repr=False)
    file_tree_dirty: bool = field(default=True, repr=False)
    file_tree_revision: int = field(default=0, repr=False)
    file_tree_events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    file_tree_subscribers: dict[str, WorkspaceTreeSubscriber] = field(default_factory=dict, repr=False)
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
        self.execution_mode = normalize_execution_mode(self.execution_mode)
        if self.execution_mode == "local":
            self.base_workspace = self.base_workspace or self.workspace
            self.worktree_path = None
            self.worktree_branch = None
        else:
            self.base_workspace = self.base_workspace or self.workspace
            self.worktree_path = self.worktree_path or self.workspace
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

    @property
    def terminal_runtime(self) -> TerminalRuntime | None:
        return self.get_terminal()

    def get_terminal(self, terminal_id: str | None = None) -> TerminalRuntime | None:
        tid = terminal_id or self.default_terminal_id
        return self.terminal_runtimes.get(tid) if tid else None

    def _ensure_default_terminal(self, workspace: str) -> None:
        if is_desktop_mode():
            return
        if self.default_terminal_id is None or self.default_terminal_id not in self.terminal_runtimes:
            self.default_terminal_id = "main"
            self.terminal_runtimes["main"] = TerminalRuntime(workspace=workspace)

    def snapshot(self, *, include_file_tree: bool = True) -> CreateSessionResponse:
        default_runtime = self.get_terminal()
        if default_runtime is not None:
            self.terminal_output = default_runtime.snapshot(self.session_id).output
        refresh_session_runtime_state(self)
        file_tree = self.get_file_tree() if include_file_tree else []
        return CreateSessionResponse(
            sessionId=self.session_id,
            model=self.model,
            modelId=self.bindings.resolve_model_reference_id(self.model, self.env_file),
            reasoningEffort=self.reasoning_effort,
            mode=self.mode,
            executionMode=self.execution_mode,
            baseWorkspace=self.base_workspace,
            worktreePath=self.worktree_path,
            worktreeBranch=self.worktree_branch,
            agentType=self.agent_type,
            phase=self.phase,
            routeState=self.route_state,
            deployState=self.deploy_state,
            planState=self.plan_state,
            isGenerating=self.is_generating,
            startupError=self.startup_error,
            envFile=self.env_file,
            workspace=self.workspace,
            workspaceOptions=self.bindings.list_workspace_options(),
            messages=self.history_messages,
            toolCalls=self.history_tools,
            thoughts=self.thoughts,
            terminalOutput=self.terminal_output,
            previewUrl=self.preview_url,
            fileTree=file_tree,
            fileTreeRevision=self.file_tree_revision,
            selectedFilePath=self.selected_file_path,
            selectedFileContent=read_text_file(self.selected_file_path, self.workspace),
            openFiles=self.open_files,
            availableSkills=list_available_skill_summaries(self.workspace),
            codeChanges=self.code_changes,
            planSteps=self.plan_steps,
        )

    def mark_file_tree_dirty(
        self,
        *,
        publish: bool = True,
        paths: list[str | Path] | None = None,
    ) -> None:
        event: dict[str, Any] | None = None
        with self.file_tree_lock:
            self.file_tree_dirty = True
            if publish:
                if paths:
                    event = self._refresh_file_tree_paths_locked(paths, reason="dirty")
                else:
                    event = self._refresh_file_tree_locked(reason="dirty")
        if event is not None:
            self._publish_file_tree_event(event)

    def _refresh_file_tree_locked(self, *, reason: str = "refresh") -> dict[str, Any]:
        self.cached_file_tree = build_file_tree_root(resolve_workspace_path(self.workspace))
        self.file_tree_loaded = True
        self.file_tree_dirty = False
        self.file_tree_revision += 1
        event = {
            "type": "tree.patch",
            "revision": self.file_tree_revision,
            "reason": reason,
            "tree": self.cached_file_tree,
        }
        self.file_tree_events = [*self.file_tree_events, event][-100:]
        return event

    def _refresh_file_tree_paths_locked(
        self,
        paths: list[str | Path],
        *,
        reason: str = "paths",
    ) -> dict[str, Any]:
        if not self.file_tree_loaded:
            return self._refresh_file_tree_locked(reason=reason)

        directories: list[dict[str, Any]] = []
        seen: set[str] = set()
        workspace_root = resolve_workspace_path(self.workspace)
        for raw_path in paths:
            target = Path(raw_path).expanduser().resolve()
            directory = target if target.is_dir() else target.parent
            if workspace_root != directory and workspace_root not in directory.parents:
                continue
            directory_key = str(directory)
            if directory_key in seen:
                continue
            seen.add(directory_key)
            node = build_directory_tree_node(directory, max_depth=1)
            directories.append(node)
            self._replace_cached_directory_node(directory_key, node)

        if not directories:
            return self._refresh_file_tree_locked(reason=reason)

        self.file_tree_loaded = True
        self.file_tree_dirty = False
        self.file_tree_revision += 1
        event = {
            "type": "tree.patch",
            "revision": self.file_tree_revision,
            "reason": reason,
            "directories": directories,
        }
        self.file_tree_events = [*self.file_tree_events, event][-100:]
        return event

    def _replace_cached_directory_node(self, directory_path: str, next_node: dict[str, Any]) -> bool:
        def replace(nodes: list[dict[str, Any]]) -> bool:
            for index, node in enumerate(nodes):
                if node.get("path") == directory_path:
                    nodes[index] = next_node
                    return True
                children = node.get("children")
                if isinstance(children, list) and replace(children):
                    return True
            return False

        if replace(self.cached_file_tree):
            return True

        workspace_root = str(resolve_workspace_path(self.workspace))
        if directory_path == workspace_root:
            self.cached_file_tree = [next_node]
            return True

        return False

    def get_file_tree(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        with self.file_tree_lock:
            if force_refresh or self.file_tree_dirty or not self.file_tree_loaded:
                event = self._refresh_file_tree_locked(reason="force" if force_refresh else "lazy")
            else:
                event = None
        if event is not None:
            self._publish_file_tree_event(event)
        with self.file_tree_lock:
            return self.cached_file_tree

    def get_file_tree_directory(self, raw_path: str, force_refresh: bool = False) -> dict[str, Any]:
        directory_path = Path(normalize_relative_path(raw_path, self.workspace))
        if not directory_path.exists() or not directory_path.is_dir():
            raise RuntimeError("目录不存在")

        with self.file_tree_lock:
            if force_refresh or not self.file_tree_loaded:
                self._refresh_file_tree_locked(reason="force" if force_refresh else "lazy")
            existing = self._find_cached_directory_node(str(directory_path))
            if (
                existing is not None
                and bool(existing.get("loaded"))
                and not force_refresh
            ):
                return existing

            node = build_directory_tree_node(directory_path, max_depth=1)
            replaced = self._replace_cached_directory_node(str(directory_path), node)
            if not replaced:
                self.cached_file_tree = build_file_tree_root(resolve_workspace_path(self.workspace))
                self._replace_cached_directory_node(str(directory_path), node)
            self.file_tree_loaded = True
            self.file_tree_dirty = False
            self.file_tree_revision += 1
            event = {
                "type": "tree.patch",
                "revision": self.file_tree_revision,
                "reason": "directory",
                "directories": [node],
            }
            self.file_tree_events = [*self.file_tree_events, event][-100:]
        self._publish_file_tree_event(event)
        return node

    def file_tree_snapshot_event(self, *, force_refresh: bool = False) -> dict[str, Any]:
        tree = self.get_file_tree(force_refresh=force_refresh)
        with self.file_tree_lock:
            return {
                "type": "tree.snapshot",
                "revision": self.file_tree_revision,
                "tree": tree,
            }

    def _find_cached_directory_node(self, directory_path: str) -> dict[str, Any] | None:
        def find(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
            for node in nodes:
                if node.get("path") == directory_path and node.get("type") == "folder":
                    return node
                children = node.get("children")
                if isinstance(children, list):
                    match = find(children)
                    if match is not None:
                        return match
            return None

        return find(self.cached_file_tree)

    def subscribe_file_tree(self, queue: asyncio.Queue[dict[str, Any] | None]) -> str:
        subscriber_id = uuid.uuid4().hex
        subscriber = WorkspaceTreeSubscriber(loop=asyncio.get_running_loop(), queue=queue)
        with self.file_tree_lock:
            self.file_tree_subscribers[subscriber_id] = subscriber
        return subscriber_id

    def unsubscribe_file_tree(self, subscriber_id: str) -> None:
        with self.file_tree_lock:
            self.file_tree_subscribers.pop(subscriber_id, None)

    def file_tree_events_since(self, revision: int) -> list[dict[str, Any]]:
        with self.file_tree_lock:
            return [event for event in self.file_tree_events if int(event.get("revision") or 0) > revision]

    def can_replay_file_tree_events_since(self, revision: int) -> bool:
        with self.file_tree_lock:
            if revision <= 0:
                return False
            if revision >= self.file_tree_revision:
                return True
            if not self.file_tree_events:
                return False
            oldest_revision = int(self.file_tree_events[0].get("revision") or 0)
            return oldest_revision <= revision + 1

    def _publish_file_tree_event(self, event: dict[str, Any]) -> None:
        with self.file_tree_lock:
            subscribers = list(self.file_tree_subscribers.values())
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)

    def get_managed_processes(self, active_only: bool = True) -> list[dict[str, Any]]:
        if self.interactive_command_session is None:
            return []
        return self.interactive_command_session.list_managed_processes(only_active=active_only)

    def terminal_snapshot(
        self,
        include_output: bool = False,
        include_file_tree: bool = False,
        include_processes: bool = False,
        terminal_id: str | None = None,
    ) -> TerminalSnapshotResponse:
        runtime = self.get_terminal(terminal_id)
        if runtime is None:
            raise RuntimeError("terminal 不存在")
        snapshot = runtime.snapshot(
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
            fileTree=self.get_file_tree(force_refresh=True) if include_file_tree else None,
            processes=self.get_managed_processes(active_only=True) if include_processes else None,
        )

    def history_snapshot(self) -> SessionHistoryItem:
        return SessionHistoryItem(
            sessionId=self.session_id,
            workspace=self.workspace,
            executionMode=self.execution_mode,
            baseWorkspace=self.base_workspace,
            worktreePath=self.worktree_path,
            worktreeBranch=self.worktree_branch,
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
        main_messages = [
            message for message in self.history_messages if not is_subagent_record(message)
        ]
        recent_messages = [
            SessionContextMessage(
                role=str(message.get("role", "")),
                content=str(message.get("content", "")),
            )
            for message in main_messages[-6:]
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
            executionMode=self.execution_mode,
            baseWorkspace=self.base_workspace,
            worktreePath=self.worktree_path,
            worktreeBranch=self.worktree_branch,
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
        self.bindings.sync_session_runtime_state_for_agent(self)
        self.bindings.persist_session_state(self)

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
            if is_subagent_record(message):
                continue
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
