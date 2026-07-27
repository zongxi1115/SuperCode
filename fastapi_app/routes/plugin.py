from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from fastapi_app.plugin_registry import get_builtin_plugin, list_builtin_plugins
from fastapi_app.project_docs_store import (
    create_project_doc,
    list_project_docs,
    read_project_docs,
    write_project_docs,
)


@dataclass(frozen=True)
class PluginRouteDeps:
    session_registry: Any
    get_loaded_plugin_ids: Callable[[Any], set[str]]
    set_loaded_plugin_ids: Callable[[Any, set[str]], None]
    rebuild_chat_session_for_agent_type: Callable[[Any, str], None]


def _plugin_payload_for_session(
    session: Any,
    plugin: dict[str, Any],
    *,
    deps: PluginRouteDeps,
) -> dict[str, Any]:
    plugin_id = str(plugin.get("id") or "").strip()
    loaded_plugins = deps.get_loaded_plugin_ids(session)
    return {
        **plugin,
        "loaded": plugin_id in loaded_plugins,
    }


def register_plugin_routes(
    app: FastAPI,
    *,
    deps: PluginRouteDeps,
) -> None:
    @app.get("/api/plugins")
    async def get_plugins() -> JSONResponse:
        return JSONResponse({"plugins": list_builtin_plugins()})

    @app.get("/api/sessions/{session_id}/plugins")
    async def get_session_plugins(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        plugins = [
            _plugin_payload_for_session(session, plugin, deps=deps)
            for plugin in list_builtin_plugins()
        ]
        return JSONResponse({"plugins": plugins})

    @app.post("/api/sessions/{session_id}/plugins/{plugin_id}/load")
    async def load_session_plugin(session_id: str, plugin_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        plugin = get_builtin_plugin(plugin_id)
        if plugin is None:
            raise HTTPException(status_code=404, detail="插件不存在")
        loaded_plugins = deps.get_loaded_plugin_ids(session)
        loaded_plugins.add(plugin.id)
        deps.set_loaded_plugin_ids(session, loaded_plugins)
        deps.rebuild_chat_session_for_agent_type(session, session.agent_type)
        session.touch()
        return JSONResponse({"plugin": _plugin_payload_for_session(session, plugin.to_payload(), deps=deps)})

    @app.post("/api/sessions/{session_id}/plugins/{plugin_id}/unload")
    async def unload_session_plugin(session_id: str, plugin_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        plugin = get_builtin_plugin(plugin_id)
        if plugin is None:
            raise HTTPException(status_code=404, detail="插件不存在")
        loaded_plugins = deps.get_loaded_plugin_ids(session)
        loaded_plugins.discard(plugin.id)
        deps.set_loaded_plugin_ids(session, loaded_plugins)
        deps.rebuild_chat_session_for_agent_type(session, session.agent_type)
        session.touch()
        return JSONResponse({"plugin": _plugin_payload_for_session(session, plugin.to_payload(), deps=deps)})

    @app.get("/api/sessions/{session_id}/project-docs")
    async def get_project_docs(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        payload = read_project_docs(session.workspace)
        session.touch()
        return JSONResponse(payload)

    @app.put("/api/sessions/{session_id}/project-docs")
    async def save_project_docs(session_id: str, body: dict[str, Any] | None = Body(None)) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        markdown = str((body or {}).get("markdown") or "")
        payload = write_project_docs(session.workspace, markdown)
        session.touch()
        return JSONResponse(payload)

    @app.get("/api/sessions/{session_id}/project-docs/documents")
    async def list_session_project_docs(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        payload = list_project_docs(session.workspace)
        session.touch()
        return JSONResponse(payload)

    @app.post("/api/sessions/{session_id}/project-docs/documents")
    async def create_session_project_doc(session_id: str, body: dict[str, Any] | None = Body(None)) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        title = str((body or {}).get("title") or "")
        payload = create_project_doc(session.workspace, title)
        session.touch()
        return JSONResponse(payload)

    @app.get("/api/sessions/{session_id}/project-docs/{document_id}")
    async def get_session_project_doc(session_id: str, document_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        payload = read_project_docs(session.workspace, document_id)
        session.touch()
        return JSONResponse(payload)

    @app.put("/api/sessions/{session_id}/project-docs/{document_id}")
    async def save_session_project_doc(
        session_id: str,
        document_id: str,
        body: dict[str, Any] | None = Body(None),
    ) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        markdown = str((body or {}).get("markdown") or "")
        payload = write_project_docs(session.workspace, markdown, document_id)
        session.touch()
        return JSONResponse(payload)
