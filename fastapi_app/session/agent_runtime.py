from __future__ import annotations

import threading
from typing import Any

from agent import Agent, ChatSession, OpenAICompatibleClient
from coding_agent import (
    CodingPromptModel,
    InteractiveCommandSession,
    build_coding_tools,
    build_project_docs_tools,
)
from deploy_agent import DeployConnectionManager, DeployPromptModel, build_deploy_tools
from fastapi_app.mcp import build_enabled_mcp_tools
from plan_agent import PlanPromptModel, build_plan_tools

from fastapi_app.agent_router import normalize_route_state
from fastapi_app.app_config import APP_DATA_ROOT, BACKEND_BASE_URL, ROOT, normalize_reasoning_effort
from fastapi_app.model_config_store import build_agent_config, resolve_model_context_tokens
from fastapi_app.rag_index import schedule_workspace_rag_index
from fastapi_app.runtime.context import infer_model_context_limit
from fastapi_app.runtime.routing import decide_route_for_message, forced_route_decision
from fastapi_app.runtime.session import (
    build_agent_runtime_state as build_agent_runtime_state_impl,
    normalize_deploy_state as normalize_deploy_state_impl,
    normalize_plan_state as normalize_plan_state_impl,
    normalize_session_phase as normalize_session_phase_impl,
    refresh_session_runtime_state as refresh_session_runtime_state_impl,
    reset_phase_for_new_turn as reset_phase_for_new_turn_impl,
    set_session_phase as set_session_phase_impl,
    sync_session_runtime_state_for_agent as sync_session_runtime_state_for_agent_impl,
    update_deploy_state as update_deploy_state_impl,
    update_plan_state as update_plan_state_impl,
)
from fastapi_app.session_history import seed_chat_session_history
from fastapi_app.workspace_utils import resolve_workspace_path


def normalize_session_phase(phase: str | None) -> str:
    return normalize_session_phase_impl(phase)


def build_agent_runtime_state(session: Any) -> dict[str, Any]:
    return build_agent_runtime_state_impl(session, APP_DATA_ROOT)


def sync_session_runtime_state_for_agent(session: Any) -> None:
    sync_session_runtime_state_for_agent_impl(session, APP_DATA_ROOT)


def normalize_plan_state(value: object) -> dict[str, Any]:
    return normalize_plan_state_impl(value)


def normalize_deploy_state(value: object) -> dict[str, Any]:
    return normalize_deploy_state_impl(value)


def refresh_session_runtime_state(session: Any) -> None:
    refresh_session_runtime_state_impl(session)


def set_session_phase(session: Any, phase: str) -> None:
    set_session_phase_impl(session, phase)


def update_deploy_state(session: Any, **updates: Any) -> None:
    update_deploy_state_impl(session, **updates)


def update_plan_state(session: Any, **updates: Any) -> None:
    update_plan_state_impl(session, **updates)


def reset_phase_for_new_turn(session: Any) -> None:
    reset_phase_for_new_turn_impl(session)


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


def get_loaded_plugin_ids(session: Any) -> set[str]:
    raw_loaded_plugins = session.route_state.get("loadedPlugins")
    if not isinstance(raw_loaded_plugins, list):
        return set()
    return {str(plugin_id).strip() for plugin_id in raw_loaded_plugins if str(plugin_id).strip()}


def set_loaded_plugin_ids(session: Any, plugin_ids: set[str]) -> None:
    session.route_state = normalize_route_state(
        {
            **session.route_state,
            "loadedPlugins": sorted(plugin_ids),
        }
    )


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
    agent.tool_context_metadata["app_data_root"] = str(APP_DATA_ROOT)
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
    loaded_plugin_ids: set[str] | None = None,
    fallback_context_tokens: int | None = None,
) -> tuple[ChatSession | None, str, str | None, str | None, str | None, int | None]:
    try:
        config, normalized_model_ref = build_agent_config(APP_DATA_ROOT, env_file)
        if reasoning_effort is not None:
            config.reasoning_effort = normalize_reasoning_effort(reasoning_effort)
        context_limit = resolve_model_context_limit(
            config.model,
            normalized_model_ref,
            fallback_context_tokens,
        )
        client = OpenAICompatibleClient(config)
        resolved_workspace = resolve_workspace_path(workspace)
        loaded_plugin_ids = loaded_plugin_ids or set()
        if agent_type == "deploy":
            model = DeployPromptModel(client, workspace=workspace)
            tools = build_deploy_tools()
        elif agent_type == "plan":
            model = PlanPromptModel(client, workspace=workspace)
            tools = build_plan_tools()
        else:
            model = CodingPromptModel(client, workspace=workspace)
            tools = build_coding_tools()
        if "project-docs" in loaded_plugin_ids:
            tools = tools + build_project_docs_tools()
        tools = tools + build_enabled_mcp_tools(APP_DATA_ROOT)
        agent = Agent(
            model=model,
            tools=tools,
            workspace=resolved_workspace,
            tool_context_metadata={
                "include_thoughts_in_context": config.include_thoughts_in_context,
                "project_root": str(ROOT),
                "app_data_root": str(APP_DATA_ROOT),
                "llm_client": client,
            },
        )
        schedule_workspace_rag_index(APP_DATA_ROOT, resolved_workspace)
        return (
            ChatSession(agent=agent),
            config.model,
            None,
            normalized_model_ref,
            config.reasoning_effort,
            context_limit,
        )
    except Exception as exc:  # noqa: BLE001 - 需要把启动失败原因回传给前端
        return None, "Demo", str(exc), None, None, None


def resolve_model_context_limit(
    model_name: str,
    env_file: str | None = None,
    fallback_context_tokens: int | None = None,
) -> int:
    provider_context_tokens = resolve_model_context_tokens(APP_DATA_ROOT, env_file)
    return provider_context_tokens or fallback_context_tokens or infer_model_context_limit(model_name)


def rebuild_chat_session_for_agent_type(session: Any, agent_type: str) -> None:
    (
        chat_session,
        model_name,
        startup_error,
        env_file_used,
        reasoning_effort,
        context_limit,
    ) = build_chat_session(
        session.workspace,
        session.env_file,
        agent_type=agent_type,
        reasoning_effort=session.reasoning_effort,
        loaded_plugin_ids=get_loaded_plugin_ids(session),
        fallback_context_tokens=session.max_context_tokens,
    )

    session.agent_type = agent_type
    session.chat_session = chat_session
    session.mode = "agent" if chat_session is not None else "demo"
    session.startup_error = startup_error
    session.env_file = env_file_used or session.env_file
    session.reasoning_effort = reasoning_effort
    if chat_session is not None:
        session.model = model_name
        session.max_context_tokens = context_limit or session.max_context_tokens
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
    session: Any,
    user_message: str,
    forced_agent_type: str | None = None,
) -> None:
    route_state = (
        forced_route_decision(session, forced_agent_type)
        if forced_agent_type
        else decide_route_for_message(session, user_message)
    )
    current_loaded_plugins = (
        session.route_state.get("loadedPlugins")
        if isinstance(session.route_state.get("loadedPlugins"), list)
        else []
    )
    next_agent_type = str(route_state.get("agentType") or session.agent_type)
    session.route_state = normalize_route_state(
        {
            **route_state,
            "loadedPlugins": current_loaded_plugins,
        }
    )
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
