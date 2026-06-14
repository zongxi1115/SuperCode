from __future__ import annotations

import json
import re
from typing import Any

from agent.llm_client import OpenAICompatibleClient


ALLOWED_AGENT_TYPES = {"chat", "coding", "deploy", "plan", "super"}


def build_default_route_state() -> dict[str, Any]:
    return {
        "agentType": "coding",
        "confidence": 0.0,
        "reason": "",
        "source": "default",
        "fallbackUsed": False,
        "keepCurrentAgent": False,
        "previousAgentType": None,
        "loadedPlugins": [],
    }


def normalize_route_state(value: object) -> dict[str, Any]:
    state = build_default_route_state()
    if isinstance(value, dict):
        for key in state:
            if key in value:
                state[key] = value[key]

    agent_type = str(state.get("agentType") or "coding").strip().lower()
    state["agentType"] = agent_type if agent_type in ALLOWED_AGENT_TYPES else "coding"

    try:
        confidence = float(state.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    state["confidence"] = max(0.0, min(confidence, 1.0))

    state["reason"] = _compact_text(str(state.get("reason") or ""), 240)

    source = str(state.get("source") or "default").strip().lower()
    state["source"] = source if source in {"model", "fallback", "forced", "default"} else "default"
    state["fallbackUsed"] = bool(state.get("fallbackUsed"))
    state["keepCurrentAgent"] = bool(state.get("keepCurrentAgent"))

    previous_agent_type = str(state.get("previousAgentType") or "").strip().lower()
    state["previousAgentType"] = previous_agent_type if previous_agent_type in ALLOWED_AGENT_TYPES else None

    raw_loaded_plugins = state.get("loadedPlugins")
    if isinstance(raw_loaded_plugins, list):
        loaded_plugins = [str(plugin_id).strip() for plugin_id in raw_loaded_plugins]
    else:
        loaded_plugins = []
    state["loadedPlugins"] = sorted({plugin_id for plugin_id in loaded_plugins if plugin_id})
    return state


def decide_agent_route_with_model(
    client: OpenAICompatibleClient,
    *,
    user_message: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    completion = client.chat_completion_messages(_build_route_messages(user_message, context))
    raw_text = completion.text.strip()
    if not raw_text:
        raise ValueError("模型路由没有返回文本内容。")
    agent_type = _parse_route_agent_type(raw_text)
    if agent_type not in ALLOWED_AGENT_TYPES:
        raise ValueError(f"模型路由返回了不支持的 agentType: {agent_type}")

    previous_agent_type = str(context.get("currentAgentType") or "").strip().lower()
    return normalize_route_state(
        {
            "agentType": agent_type,
            "confidence": 0.8,
            "reason": "模型路由选择。",
            "source": "model",
            "fallbackUsed": False,
            "keepCurrentAgent": agent_type == previous_agent_type,
            "previousAgentType": previous_agent_type if previous_agent_type in ALLOWED_AGENT_TYPES else None,
        }
    )


def _build_route_messages(user_message: str, context: dict[str, Any]) -> list[dict[str, object]]:
    pending = context.get("pending") if isinstance(context.get("pending"), dict) else {}
    plan = context.get("plan") if isinstance(context.get("plan"), dict) else {}
    deploy = context.get("deploy") if isinstance(context.get("deploy"), dict) else {}
    workspace = context.get("workspace") if isinstance(context.get("workspace"), dict) else {}
    compact_context = {
        "current": context.get("currentAgentType"),
        "phase": context.get("phase"),
        "pendingConnect": bool(pending.get("connectRequests")),
        "pendingPlanQuestions": bool(pending.get("planQuestions")),
        "planStatus": plan.get("status"),
        "planDraft": bool(plan.get("hasDraft")),
        "planSubmitted": bool(plan.get("hasSubmittedPlan")),
        "pendingCodingInput": bool(plan.get("pendingCodingInput")),
        "deployActive": bool(deploy.get("hasActiveSession")),
        "deployPendingInput": deploy.get("pendingInputKind"),
        "workspaceEmpty": bool(workspace.get("looksEmpty")),
        "selectedFile": workspace.get("selectedFilePath"),
        "recentUser": context.get("recentUserMessages"),
    }
    system_prompt = (
        "你是 SuperCode 的轻量路由器。只输出一个词：chat、coding、plan、deploy 或 super。\n"
        "chat=普通闲聊/常识问答/不需要项目上下文或工具的直接回答；plan=澄清需求/调研/实施计划；coding=改代码/调试/测试/解释代码；deploy=部署/上传/服务器/环境变量/发布/回滚/远程连接；super=用户明确选择超能模式，或 current 已是 super 且用户只是泛化追问/继续。\n"
        "不要主动把普通请求升级到 super。若用户在回答计划问题选 plan；在提供部署连接信息选 deploy；已提交计划进入执行选 coding；泛化追问保持 current。\n"
        "禁止 JSON、Markdown、解释和标点。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "message": user_message,
                    "context": compact_context,
                },
                ensure_ascii=False,
            ),
        },
    ]


def _parse_route_agent_type(raw_text: str) -> str:
    stripped = raw_text.strip().lower()
    if stripped in ALLOWED_AGENT_TYPES:
        return stripped
    try:
        payload = _parse_json_object(stripped)
    except (ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        candidate = str(payload.get("agentType") or payload.get("agent") or payload.get("route") or "").strip().lower()
        if candidate in ALLOWED_AGENT_TYPES:
            return candidate
    matched = [agent_type for agent_type in ALLOWED_AGENT_TYPES if re.search(rf"\b{agent_type}\b", stripped)]
    if len(matched) == 1:
        return matched[0]
    return stripped


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型路由返回的 JSON 不是对象。")
    return parsed


def _compact_text(value: str, limit: int) -> str:
    compact = " ".join(value.split()).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."
