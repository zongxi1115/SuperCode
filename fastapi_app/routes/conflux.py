from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from conflux_agents.config import ConfluxConfig
from conflux_agents.store import ConfluxConfigStore


SPECIALIST_TEMPLATES: list[dict[str, str]] = [
    {
        "label": "Python 后端",
        "template": "精通 Python 3.12、FastAPI、Pydantic v2、SQLite 和异步任务编排，擅长后端接口、配置存储、数据校验和错误处理；不负责前端视觉实现。",
    },
    {
        "label": "React 前端",
        "template": "精通 React 19、Vite、Tailwind v4 和组件化表单，擅长把复杂配置界面做得清晰可维护；不熟悉后端持久化细节。",
    },
    {
        "label": "代码审计",
        "template": "擅长审查 git diff、发现回归风险、检查边界条件和安全约束，会优先指出可能破坏用户数据或现有流程的问题。",
    },
    {
        "label": "测试验证",
        "template": "擅长为已有代码选择轻量验证方式，优先使用语法检查、类型检查和最小复现，不主动扩大测试范围。",
    },
    {
        "label": "文档写作",
        "template": "擅长中英文 Markdown 文档、变更说明和用户向导，能把实现细节整理成开发者容易理解的维护说明。",
    },
    {
        "label": "Tauri 桌面",
        "template": "熟悉 Tauri 桌面壳、前后端通信、Windows 路径兼容和本地优先应用约束，擅长排查桌面环境差异。",
    },
    {
        "label": "DevOps 部署",
        "template": "熟悉部署脚本、环境变量、Vercel、服务器连接和发布回滚流程，擅长发现运行环境与构建配置问题。",
    },
    {
        "label": "架构整理",
        "template": "擅长在不大规模重构的前提下梳理模块边界、命名和数据流，保持业务流程连贯，避免过度抽象。",
    },
]


@dataclass(frozen=True)
class ConfluxRouteDeps:
    app_data_root: Path


class ConfluxChatPlaceholderRequest(BaseModel):
    message: str = ""
    agent_type: str | None = None
    agent_mode: str | None = None


def register_conflux_routes(
    app: FastAPI,
    *,
    deps: ConfluxRouteDeps,
) -> None:
    def build_store() -> ConfluxConfigStore:
        return ConfluxConfigStore(root=deps.app_data_root)

    @app.get("/api/conflux/config")
    async def get_conflux_config() -> JSONResponse:
        config = await asyncio.to_thread(build_store().load)
        if config is None:
            return JSONResponse({"configured": False, "config": None})
        return JSONResponse({"configured": True, "config": config.model_dump(mode="json")})

    @app.put("/api/conflux/config")
    async def put_conflux_config(payload: ConfluxConfig) -> JSONResponse:
        await asyncio.to_thread(build_store().save, payload)
        return JSONResponse({"ok": True})

    @app.get("/api/conflux/specialist-templates")
    async def get_specialist_templates() -> list[dict[str, Any]]:
        return SPECIALIST_TEMPLATES

    @app.post("/api/chat")
    async def conflux_chat_placeholder(payload: ConfluxChatPlaceholderRequest) -> JSONResponse:
        agent_type = str(payload.agent_type or payload.agent_mode or "").strip().lower()
        if agent_type != "conflux":
            raise HTTPException(status_code=400, detail="请使用 /api/chat/stream 启动普通对话。")
        return JSONResponse(
            status_code=501,
            content={"detail": "Conflux orchestrator not yet implemented, coming in Step 6"},
        )
