from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from agent import Agent, ChatSession, OpenAICompatibleClient
from chat_agent import ChatPromptModel
from deploy_agent import DeployPromptModel, build_deploy_tools
from coding_agent import CodingPromptModel, build_coding_tools, build_project_docs_tools
from plan_agent import PlanPromptModel, build_plan_tools
from fastapi_app.api_models import (
    EmbeddingSettingsPayload,
    ModelConfigPayload,
    SettingsPayload,
    SwitchModelRequest,
    UIModelProviderPayload,
)
from fastapi_app.model_config_store import (
    build_agent_config,
    config_store_path,
    discover_provider_model_catalog,
    list_model_options,
    load_ui_model_providers,
    save_ui_model_providers,
    scan_env_model_sources,
)
from fastapi_app.mcp import build_enabled_mcp_tools
from fastapi_app.session.agent_runtime import resolve_model_context_limit
from fastapi_app.rag_index import schedule_workspace_rag_index, test_embedding_config
from fastapi_app.session_history import seed_chat_session_history
from fastapi_app.workspace_utils import resolve_workspace_path


@dataclass(frozen=True)
class ConfigRouteDeps:
    app_data_root: Any
    require_session: Callable[[str], Any]
    resolve_model_option: Callable[[str | None, str | None], dict[str, str]]
    resolve_model_reference_id: Callable[[str | None, str | None], str | None]
    normalize_reasoning_effort: Callable[[str | None], str | None]
    attach_agent_runtime_metadata: Callable[..., None]
    sync_session_runtime_state_for_agent: Callable[[Any], None]
    invalidate_session_context_usage: Callable[[Any], None]
    get_loaded_plugin_ids: Callable[[Any], set[str]]


def register_config_routes(
    app: FastAPI,
    *,
    deps: ConfigRouteDeps,
) -> None:
    @app.get("/api/models")
    async def get_models() -> JSONResponse:
        models = await asyncio.to_thread(list_model_options, deps.app_data_root)
        return JSONResponse({"models": models})

    @app.get("/api/model-configs")
    async def get_model_configs() -> JSONResponse:
        providers, env_configs = await asyncio.gather(
            asyncio.to_thread(load_ui_model_providers, deps.app_data_root),
            asyncio.to_thread(scan_env_model_sources, deps.app_data_root),
        )
        return JSONResponse(
            {
                "providers": providers,
                "envConfigs": env_configs,
                "configPath": str(config_store_path(deps.app_data_root)),
            }
        )

    @app.put("/api/model-configs")
    async def update_model_configs(payload: ModelConfigPayload) -> JSONResponse:
        providers = await asyncio.to_thread(
            save_ui_model_providers,
            deps.app_data_root,
            [provider.model_dump(exclude_none=True) for provider in payload.providers],
            refresh_context=False,
        )
        return JSONResponse(
            {
                "providers": providers,
                "envConfigs": scan_env_model_sources(deps.app_data_root),
                "configPath": str(config_store_path(deps.app_data_root)),
            }
        )

    @app.post("/api/model-configs/discover-models")
    async def discover_models(payload: UIModelProviderPayload) -> JSONResponse:
        try:
            catalog = await asyncio.to_thread(
                discover_provider_model_catalog,
                payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(catalog)

    @app.get("/api/settings")
    async def get_settings() -> JSONResponse:
        from fastapi_app.settings_store import load_settings
        from fastapi_app.memory_store import load_memory_settings

        settings = load_settings(deps.app_data_root)
        settings["memory"] = load_memory_settings(deps.app_data_root)
        return JSONResponse(settings)

    @app.put("/api/settings")
    async def update_settings(payload: SettingsPayload) -> JSONResponse:
        from fastapi_app.memory_store import save_memory_settings
        from fastapi_app.settings_store import save_settings

        raw_payload = payload.model_dump(by_alias=True)
        memory_payload = raw_payload.get("memory") if isinstance(raw_payload.get("memory"), dict) else {}
        base_payload = {**raw_payload}
        base_payload.pop("memory", None)
        merged = save_settings(deps.app_data_root, base_payload)
        merged["memory"] = save_memory_settings(
            deps.app_data_root,
            enabled=bool(memory_payload.get("enabled", True)),
            auto_learn=bool(memory_payload.get("autoLearn", True)),
            global_items=memory_payload.get("global", []) if isinstance(memory_payload.get("global"), list) else [],
            workspace_items=(
                memory_payload.get("workspaces")
                if isinstance(memory_payload.get("workspaces"), dict)
                else {}
            ),
        )
        return JSONResponse(merged)

    @app.post("/api/settings/embedding/test")
    async def test_embedding_settings(payload: EmbeddingSettingsPayload) -> JSONResponse:
        try:
            result = await asyncio.to_thread(
                test_embedding_config,
                payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    @app.put("/api/sessions/{session_id}/model")
    async def switch_session_model(session_id: str, request: SwitchModelRequest) -> JSONResponse:
        session = deps.require_session(session_id)
        model_option = deps.resolve_model_option(request.model, request.env_file)
        model_ref = model_option["envFile"]
        provided_fields = set(getattr(request, "model_fields_set", set()))
        try:
            reasoning_effort = (
                deps.normalize_reasoning_effort(request.reasoning_effort)
                if "reasoning_effort" in provided_fields
                else session.reasoning_effort
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            config, normalized_model_ref = build_agent_config(deps.app_data_root, model_ref)
            config.reasoning_effort = reasoning_effort
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        client = OpenAICompatibleClient(config)
        if session.agent_type == "deploy":
            model = DeployPromptModel(client, workspace=session.workspace)
            tools = build_deploy_tools()
        elif session.agent_type == "plan":
            model = PlanPromptModel(client, workspace=session.workspace)
            tools = build_plan_tools()
        elif session.agent_type == "chat":
            model = ChatPromptModel(client)
            tools = []
        else:
            model = CodingPromptModel(client, workspace=session.workspace)
            tools = build_coding_tools()
        if session.agent_type != "chat" and "project-docs" in deps.get_loaded_plugin_ids(session):
            tools = tools + build_project_docs_tools()
        if session.agent_type != "chat":
            tools = tools + build_enabled_mcp_tools(deps.app_data_root)
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
        schedule_workspace_rag_index(deps.app_data_root, session.workspace)
        seed_chat_session_history(session.chat_session, session.history_messages, session.history_tools)
        if isinstance(session.chat_session.agent, Agent):
            deps.attach_agent_runtime_metadata(
                session.chat_session.agent,
                session_id=session.session_id,
                interactive_command_session=interactive_command_session,
                cancel_event=session.cancel_event,
                include_thoughts_in_context=config.include_thoughts_in_context,
                deploy_connection_manager=session.deploy_connection_manager,
            )
            deps.sync_session_runtime_state_for_agent(session)
        session.model = config.model
        session.max_context_tokens = resolve_model_context_limit(session.model, normalized_model_ref)
        session.reasoning_effort = config.reasoning_effort
        session.env_file = normalized_model_ref
        session.mode = "agent"
        session.startup_error = None
        deps.invalidate_session_context_usage(session)
        session.touch()

        return JSONResponse({
            "model": session.model,
            "modelId": deps.resolve_model_reference_id(session.model, session.env_file),
            "reasoningEffort": session.reasoning_effort,
            "mode": session.mode,
            "agentType": session.agent_type,
            "phase": session.phase,
            "routeState": session.route_state,
            "deployState": session.deploy_state,
            "planState": session.plan_state,
            "envFile": session.env_file,
            "maxTokens": session.max_context_tokens,
            "previewUrl": session.preview_url,
        })

