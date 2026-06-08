from __future__ import annotations

from urllib.parse import unquote

from fastapi import HTTPException

from fastapi_app.app_config import APP_DATA_ROOT, DEFAULT_WORKSPACE
from fastapi_app.model_config_store import resolve_model_option as resolve_stored_model_option
from fastapi_app.workspace_utils import (
    list_workspace_options as list_workspace_options_impl,
    normalize_workspace as normalize_workspace_impl,
)


def normalize_workspace(raw_workspace: str | None) -> str:
    return normalize_workspace_impl(raw_workspace, DEFAULT_WORKSPACE)


def normalize_workspace_identifier(workspace_id: str) -> str:
    decoded = unquote(str(workspace_id or "").strip())
    if not decoded:
        raise HTTPException(status_code=400, detail="工作区不能为空。")
    return normalize_workspace(decoded)


def list_workspace_options() -> list[dict[str, str]]:
    return list_workspace_options_impl(DEFAULT_WORKSPACE)


def resolve_model_option(model_name: str | None, env_file: str | None = None) -> dict[str, str]:
    try:
        return resolve_stored_model_option(APP_DATA_ROOT, model_name, env_file)
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
