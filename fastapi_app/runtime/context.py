from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException

from agent import OpenAICompatibleClient
from fastapi_app.api_models import (
    SessionContextCompressionRequest,
    SessionContextCompressionResponse,
    SessionContextResponse,
)
from fastapi_app.model_config_store import build_agent_config
from fastapi_app.session_history import seed_chat_session_history

DEFAULT_CONTEXT_COMPRESSION_USAGE_THRESHOLD = 0.8
DEFAULT_CONTEXT_COMPRESSION_RECENT_MESSAGES = 6
DEFAULT_CONTEXT_COMPRESSION_RECENT_TOOLS = 8
DEFAULT_CONTEXT_COMPRESSION_RECENT_THOUGHTS = 4
MAX_CONTEXT_COMPRESSION_SOURCE_MESSAGES = 24
MAX_CONTEXT_COMPRESSION_SOURCE_TOOLS = 20
MAX_CONTEXT_COMPRESSION_SOURCE_THOUGHTS = 10
MAX_CONTEXT_COMPRESSION_SOURCE_CODE_CHANGES = 8
CONTEXT_COMPRESSION_SUMMARY_PREFIX = "[会话压缩摘要]"


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
        try:
            value = int(raw_usage.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        usage[key] = max(value, 0)
    if usage["totalTokens"] == 0:
        usage["totalTokens"] = usage["inputTokens"] + usage["outputTokens"]
    return usage


def infer_model_context_limit(model_name: str) -> int:
    normalized = model_name.lower()
    if "claude" in normalized:
        return 200_000
    if "gpt-4.1" in normalized:
        return 1_047_576
    if "gpt-5-chat" in normalized:
        return 128_000
    if "gpt-5.5" in normalized:
        return 1_050_000
    if "gpt-5.4-mini" in normalized or "gpt-5.4-nano" in normalized:
        return 400_000
    if "gpt-5.4" in normalized:
        return 1_050_000
    if "gpt-5" in normalized:
        return 400_000
    if "qwen" in normalized:
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


def estimate_session_tokens(session: Any) -> int:
    return _estimate_context_tokens_from_parts(
        session.history_messages,
        session.thoughts,
        session.history_tools,
        session.workspace,
    )


def estimate_session_context_tokens(session: Any) -> int:
    token_usage = normalize_session_token_usage(session.token_usage)
    if token_usage["inputTokens"] > 0:
        return token_usage["inputTokens"]
    return estimate_session_tokens(session)


def invalidate_session_context_usage(session: Any) -> None:
    session.token_usage = _empty_session_token_usage()


def add_cumulative_session_token_usage(session: Any, usage: dict[str, int] | None) -> None:
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


def merge_session_token_usage(session: Any, usage: dict[str, int] | None) -> None:
    normalized_usage = normalize_session_token_usage(usage)
    if not any(normalized_usage.values()):
        return

    session.token_usage = normalized_usage
    add_cumulative_session_token_usage(session, normalized_usage)


def build_session_state_payload(session: Any) -> dict[str, Any]:
    return {
        "workspace": session.workspace,
        "executionMode": session.execution_mode,
        "baseWorkspace": session.base_workspace,
        "worktreePath": session.worktree_path,
        "worktreeBranch": session.worktree_branch,
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


@dataclass(slots=True)
class ContextCompressionSlices:
    archived_messages: list[dict[str, Any]]
    preserved_messages: list[dict[str, Any]]
    archived_tools: list[dict[str, Any]]
    preserved_tools: list[dict[str, Any]]
    archived_thoughts: list[str]
    preserved_thoughts: list[str]


@dataclass(frozen=True)
class ContextRuntimeDeps:
    app_data_root: Any
    normalize_reasoning_effort: Callable[[str | None], str | None]
    resolve_model_option: Callable[[str | None, str | None], dict[str, str]]
    sync_session_runtime_state_for_agent: Callable[[Any], None]


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
    session: Any,
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
    session: Any,
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
    session: Any,
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
    session: Any,
    source_text: str,
    instruction: str | None,
    deps: ContextRuntimeDeps,
) -> str:
    model_ref = session.env_file
    if not model_ref:
        try:
            model_ref = deps.resolve_model_option(session.model, None)["envFile"]
        except HTTPException:
            model_ref = None
    config, _normalized_model_ref = build_agent_config(deps.app_data_root, model_ref)
    if session.reasoning_effort:
        config.reasoning_effort = deps.normalize_reasoning_effort(session.reasoning_effort)
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
    session: Any,
    request: SessionContextCompressionRequest,
    *,
    deps: ContextRuntimeDeps,
    summarizer: Callable[[Any, str, str | None, ContextRuntimeDeps], str] | None = None,
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
            summarizer(session, source_text, request.instruction, deps)
            if summarizer is not None
            else _summarize_context_with_model(session, source_text, request.instruction, deps)
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
            deps.sync_session_runtime_state_for_agent(session)
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
    session: Any,
    *,
    deps: ContextRuntimeDeps,
) -> SessionContextCompressionResponse | None:
    response = compress_session_context(
        session,
        SessionContextCompressionRequest(
            mode="apply",
            usageThreshold=DEFAULT_CONTEXT_COMPRESSION_USAGE_THRESHOLD,
        ),
        deps=deps,
    )
    return response if response.applied else None
