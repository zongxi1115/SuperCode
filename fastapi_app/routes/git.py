from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from coding_agent.git_tools import execute_git_commit, execute_git_tag, init_git_repo
from fastapi_app.api_models import GitCommitRequest, GitTagRequest
from fastapi_app.workspace_utils import resolve_workspace_path


@dataclass(frozen=True)
class GitRouteDeps:
    session_registry: Any
    hidden_windows_process_kwargs: Callable[[], dict[str, Any]]


async def _run_git_subprocess(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
    deps: GitRouteDeps,
) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(
        subprocess.run,
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **deps.hidden_windows_process_kwargs(),
    )


def register_git_routes(
    app: FastAPI,
    *,
    deps: GitRouteDeps,
) -> None:
    @app.post("/api/sessions/{session_id}/git/init")
    async def git_init(session_id: str) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
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
        session = deps.session_registry.require_session(session_id)
        workspace = resolve_workspace_path(session.workspace)
        if not (workspace / ".git").exists():
            return JSONResponse({"commits": [], "isRepo": False})
        try:
            safe_count = min(max(count, 1), 100)
            result = await _run_git_subprocess(
                ["git", "log", f"-{safe_count}", "--pretty=format:%h|%an|%ai|%s"],
                cwd=workspace,
                timeout=15,
                deps=deps,
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

            status_result = await _run_git_subprocess(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                timeout=10,
                deps=deps,
            )
            changed_files = (
                [line.strip() for line in status_result.stdout.strip().splitlines() if line.strip()]
                if status_result.stdout.strip()
                else []
            )

            branch_result = await _run_git_subprocess(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=workspace,
                timeout=5,
                deps=deps,
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
        session = deps.session_registry.require_session(session_id)
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
        session = deps.session_registry.require_session(session_id)
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
        session = deps.session_registry.require_session(session_id)
        workspace = resolve_workspace_path(session.workspace)
        if not (workspace / ".git").exists():
            return JSONResponse({"tags": [], "isRepo": False})
        try:
            result = await _run_git_subprocess(
                ["git", "tag", "-l", "--sort=-creatordate", "--format=%(refname:short)|%(creatordate:short)|%(subject)"],
                cwd=workspace,
                timeout=10,
                deps=deps,
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
        session = deps.session_registry.require_session(session_id)
        workspace = resolve_workspace_path(session.workspace)
        if not (workspace / ".git").exists():
            return JSONResponse({"isRepo": False, "changedFiles": [], "branch": ""})
        try:
            status_result = await _run_git_subprocess(
                ["git", "status", "--porcelain"],
                cwd=workspace,
                timeout=10,
                deps=deps,
            )
            changed_files = (
                [line.strip() for line in status_result.stdout.strip().splitlines() if line.strip()]
                if status_result.stdout.strip()
                else []
            )

            branch_result = await _run_git_subprocess(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=workspace,
                timeout=5,
                deps=deps,
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

            return JSONResponse({"isRepo": True, "changedFiles": changed_files, "branch": branch})
        except Exception as exc:
            return JSONResponse({"isRepo": True, "changedFiles": [], "branch": "", "error": str(exc)}, status_code=500)
