from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Protocol

from agent import OpenAICompatibleClient
from coding_agent.tool_common import DEFAULT_IGNORED_DIR_NAMES

from fastapi_app.agent_router import decide_agent_route_with_model, normalize_route_state
from fastapi_app.app_config import APP_DATA_ROOT
from fastapi_app.runtime.context import compact_text
from fastapi_app.model_config_store import build_agent_config
from fastapi_app.runtime.session import normalize_deploy_state, normalize_plan_state
from fastapi_app.workspace_utils import resolve_workspace_path

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

CHAT_ROUTE_KEYWORDS = (
    "chat mode",
    "chat模式",
    "聊天",
    "闲聊",
    "普通对话",
)

SUPER_ROUTE_KEYWORDS = (
    "super mode",
    "超能模式",
    "超能智能体",
    "超能agent",
    "超能 agent",
)

PLAIN_CHAT_QUESTION_KEYWORDS = (
    "是什么",
    "为什么",
    "怎么",
    "如何",
    "what is",
    "why",
    "how",
)

CHAT_EXACT_MESSAGES = {
    "hi",
    "hello",
    "hey",
    "你好",
    "您好",
    "在吗",
}

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

PATH_HINT_PATTERN = re.compile(
    r"[\w./-]+\.(ts|tsx|js|jsx|py|go|rs|java|kt|swift|vue|svelte|json|yml|yaml|css|scss|html|md)\b"
)
ROUTING_SPECIFICITY_KEYWORDS = ("api", "接口", "组件", "函数", "页面", "数据库", "表", "测试")


class RoutingSession(Protocol):
    agent_type: str
    workspace: str
    selected_file_path: str | None
    history_messages: list[dict[str, Any]]
    pending_connect_requests: list[dict[str, Any]]
    pending_user_input_requests: list[dict[str, Any]]
    plan_state: object
    deploy_state: object
    phase: str
    mode: str
    env_file: str | None


def _normalized_message_for_routing(user_message: str) -> str:
    return " ".join(user_message.strip().lower().split())


def _contains_any_keyword(text: str, keywords: tuple[str, ...] | set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _message_has_specific_path_hint(text: str) -> bool:
    return bool(
        PATH_HINT_PATTERN.search(text)
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
    if any(keyword in text for keyword in ROUTING_SPECIFICITY_KEYWORDS):
        return False
    return len(text) <= 16


def _is_plain_chat_question(text: str) -> bool:
    if _message_has_specific_path_hint(text):
        return False
    if _contains_any_keyword(text, DEPLOY_ROUTE_KEYWORDS):
        return False
    if _contains_any_keyword(text, PLAN_ROUTE_KEYWORDS):
        return False
    if _contains_any_keyword(text, CODING_ROUTE_KEYWORDS):
        return False
    return text.endswith("?") or text.endswith("？") or _contains_any_keyword(text, PLAIN_CHAT_QUESTION_KEYWORDS)


def _is_plan_session_active(session: RoutingSession) -> bool:
    if session.agent_type != "plan":
        return False
    plan_state = normalize_plan_state(session.plan_state)
    return plan_state.get("status") != "submitted"


def _should_force_plan_route(session: RoutingSession, text: str) -> bool:
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


def route_agent_type_for_message(session: RoutingSession, user_message: str) -> str:
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

    if text in CHAT_EXACT_MESSAGES:
        return "chat"
    if _contains_any_keyword(text, SUPER_ROUTE_KEYWORDS):
        return "super"
    if _contains_any_keyword(text, CODING_ROUTE_KEYWORDS):
        return "coding"
    if session.agent_type == "chat" and text in ROUTER_GENERIC_FOLLOWUPS:
        return "chat"
    if session.agent_type == "super" and text in ROUTER_GENERIC_FOLLOWUPS:
        return "super"
    if active_deploy_session and text in ROUTER_GENERIC_FOLLOWUPS:
        return "deploy"
    if active_deploy_session and session.agent_type == "deploy":
        return "deploy"
    if (
        _contains_any_keyword(text, CHAT_ROUTE_KEYWORDS)
        or (session.agent_type == "chat" and _is_plain_chat_question(text))
        or (not session.history_messages and _is_plain_chat_question(text))
    ):
        return "chat"
    if _should_force_plan_route(session, text):
        return "plan"
    if _contains_any_keyword(text, DEPLOY_ROUTE_KEYWORDS):
        return "deploy"
    if _is_plan_session_active(session):
        return "plan"
    return "coding"


def fallback_route_decision(
    session: RoutingSession,
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


def forced_route_decision(session: RoutingSession, agent_type: str) -> dict[str, Any]:
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


def _find_active_task_title(plan_state: dict[str, Any]) -> str | None:
    raw_tasks = plan_state.get("tasks")
    if not isinstance(raw_tasks, list):
        return None

    active_task_id = str(plan_state.get("active_task_id") or "").strip()
    active_task: dict[str, Any] | None = None
    if active_task_id:
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("id") or "").strip() == active_task_id:
                active_task = task
                break

    if active_task is None:
        active_task = next(
            (
                task
                for task in raw_tasks
                if isinstance(task, dict) and str(task.get("status") or "").strip().lower() == "running"
            ),
            None,
        )

    title = str((active_task or {}).get("title") or "").strip()
    return title or None


def _build_router_workspace_summary(session: RoutingSession) -> dict[str, Any]:
    return {
        "looksEmpty": _workspace_looks_empty(session.workspace),
        "selectedFilePath": session.selected_file_path,
    }


def _build_router_plan_summary(session: RoutingSession) -> dict[str, Any]:
    plan_state = normalize_plan_state(session.plan_state)
    draft = plan_state.get("draft") if isinstance(plan_state.get("draft"), dict) else None
    submitted = (
        plan_state.get("last_submitted_plan")
        if isinstance(plan_state.get("last_submitted_plan"), dict)
        else None
    )
    return {
        "status": plan_state.get("status"),
        "hasDraft": bool(draft),
        "hasSubmittedPlan": bool(submitted),
        "draftTitle": str((draft or {}).get("title") or "").strip() or None,
        "submittedTitle": str((submitted or {}).get("title") or "").strip() or None,
        "pendingCodingInput": bool(plan_state.get("pending_coding_input")),
        "activeTaskTitle": _find_active_task_title(plan_state),
        "activeStepId": plan_state.get("active_step_id"),
    }


def _build_router_deploy_summary(session: RoutingSession) -> dict[str, Any]:
    deploy_state = normalize_deploy_state(session.deploy_state)
    return {
        "hasActiveSession": bool(deploy_state.get("active_session_id")),
        "activeDisplayName": deploy_state.get("active_display_name"),
        "activeHost": deploy_state.get("active_host"),
        "pendingInputKind": deploy_state.get("pending_input_kind"),
        "connectionCount": deploy_state.get("connection_count"),
    }


def _build_router_context(session: RoutingSession) -> dict[str, Any]:
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


def decide_route_for_message(session: RoutingSession, user_message: str) -> dict[str, Any]:
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
        return fallback_route_decision(session, user_message, reason="当前正在等待部署连接信息，保持部署智能体。")
    if session.pending_user_input_requests:
        return fallback_route_decision(session, user_message, reason="当前正在等待计划问题回答，保持计划智能体。")
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
        return fallback_route_decision(session, user_message, reason="真实模型运行时不可用，已使用规则兜底选择智能体。")

    try:
        config, _model_ref = build_agent_config(APP_DATA_ROOT, session.env_file)
        config.reasoning_effort = None
        return decide_agent_route_with_model(
            OpenAICompatibleClient(config),
            user_message=user_message,
            context=_build_router_context(session),
        )
    except Exception as exc:  # noqa: BLE001 - 路由失败必须降级，不能阻断聊天
        return fallback_route_decision(
            session,
            user_message,
            reason=f"模型路由失败，已使用规则兜底。原因：{compact_text(str(exc), 160)}",
        )

