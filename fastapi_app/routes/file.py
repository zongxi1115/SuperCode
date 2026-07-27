from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from fastapi_app.code_changes import ensure_code_change_baseline, record_code_change, relative_workspace_path
from fastapi_app.app_config import APP_DATA_ROOT
from fastapi_app.rag_index import schedule_workspace_rag_index
from fastapi_app.ui_message_stream import sse_data
from fastapi_app.workspace_utils import normalize_relative_path, read_text_file, resolve_preview_path, resolve_workspace_path

SUPPORTED_EDITOR_COMMANDS = {
    "code",
    "code-insiders",
    "cursor",
    "zed",
    "devenv",
    "subl",
    "webstorm",
}

PREVIEW_SELECT_BRIDGE_SCRIPT = r"""
(() => {
  const READY = "SC_SELECT_BRIDGE_READY";
  const PING = "SC_SELECT_BRIDGE_PING";
  const START = "SC_SELECT_START";
  const CANCEL = "SC_SELECT_CANCEL";
  const RESULT = "SC_SELECT_RESULT";
  const ERROR = "SC_SELECT_ERROR";
  const HOVER_CLASS = "__sc-select-hover";
  const SELECTED_CLASS = "__sc-select-selected";
  const STYLE_ID = "__sc-select-bridge-style";

  if (window.__SUPER_CODE_SELECT_BRIDGE__) {
    window.parent?.postMessage({ type: READY, sourceUrl: window.location.href }, "*");
    return;
  }

  window.__SUPER_CODE_SELECT_BRIDGE__ = true;

  let selecting = false;
  let activeTarget = null;

  const post = (message) => {
    try {
      window.parent?.postMessage({ ...message, sourceUrl: window.location.href }, "*");
    } catch (error) {
      console.warn("[SuperCode] select bridge postMessage failed", error);
    }
  };

  const ensureStyle = () => {
    let style = document.getElementById(STYLE_ID);
    if (style) return style;
    style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      * { cursor: crosshair !important; }
      .${HOVER_CLASS} {
        outline: 2px dashed #3b82f6 !important;
        outline-offset: 2px !important;
        background-color: rgba(59, 130, 246, 0.1) !important;
      }
      .${SELECTED_CLASS} {
        outline: 2px solid #3b82f6 !important;
        outline-offset: 2px !important;
        background-color: rgba(59, 130, 246, 0.15) !important;
      }
    `;
    document.head.appendChild(style);
    return style;
  };

  const clearClasses = () => {
    document.querySelectorAll(`.${HOVER_CLASS}, .${SELECTED_CLASS}`).forEach((el) => {
      el.classList.remove(HOVER_CLASS, SELECTED_CLASS);
    });
    activeTarget = null;
  };

  const cleanup = () => {
    selecting = false;
    clearClasses();
    document.getElementById(STYLE_ID)?.remove();
    document.removeEventListener("mouseover", handleMouseOver, true);
    document.removeEventListener("mouseout", handleMouseOut, true);
    document.removeEventListener("click", handleClick, true);
    document.removeEventListener("keydown", handleKeyDown, true);
  };

  const getElementSelector = (el) => {
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE) {
      let selector = current.tagName.toLowerCase();
      if (current.id) {
        selector += `#${CSS.escape(current.id)}`;
        parts.unshift(selector);
        break;
      }

      const classes = Array.from(current.classList || [])
        .filter((className) => className && !className.startsWith("__sc-select"));
      if (classes.length) {
        selector += classes.map((className) => `.${CSS.escape(className)}`).join("");
      }

      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(
          (sibling) => sibling.tagName === current.tagName,
        );
        if (siblings.length > 1) {
          selector += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        }
      }

      parts.unshift(selector);
      current = current.parentElement;
    }
    return parts.slice(-4).join(" > ");
  };

  function shouldIgnoreTarget(target) {
    return (
      !target ||
      !(target instanceof HTMLElement) ||
      target === document.body ||
      target === document.documentElement
    );
  }

  function handleMouseOver(event) {
    if (!selecting) return;
    event.stopPropagation();
    const target = event.target;
    if (shouldIgnoreTarget(target)) return;
    if (activeTarget && activeTarget !== target) {
      activeTarget.classList.remove(HOVER_CLASS);
    }
    activeTarget = target;
    target.classList.add(HOVER_CLASS);
  }

  function handleMouseOut(event) {
    if (!selecting) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
      target.classList.remove(HOVER_CLASS);
    }
  }

  function handleClick(event) {
    if (!selecting) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.target;
    if (shouldIgnoreTarget(target)) return;

    try {
      clearClasses();
      target.classList.add(SELECTED_CLASS);
      const selector = getElementSelector(target);
      const html = target.outerHTML;
      cleanup();
      post({ type: RESULT, selector, html });
    } catch (error) {
      cleanup();
      post({
        type: ERROR,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Escape") {
      cleanup();
      post({ type: CANCEL });
    }
  }

  const start = () => {
    if (selecting) return;
    selecting = true;
    ensureStyle();
    document.addEventListener("mouseover", handleMouseOver, true);
    document.addEventListener("mouseout", handleMouseOut, true);
    document.addEventListener("click", handleClick, true);
    document.addEventListener("keydown", handleKeyDown, true);
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const type = event.data?.type;
    if (type === START) {
      start();
      return;
    }
    if (type === PING) {
      post({ type: READY });
      return;
    }
    if (type === CANCEL) {
      cleanup();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => post({ type: READY }), { once: true });
  } else {
    post({ type: READY });
  }
})();
"""


@dataclass(frozen=True)
class FileRouteDeps:
    session_registry: Any


def resolve_workspace_target(
    session_id: str,
    path: str,
    *,
    deps: FileRouteDeps,
) -> tuple[Any, Path, str]:
    session = deps.session_registry.require_session(session_id)
    resolved_path = normalize_relative_path(path, session.workspace)
    target = Path(resolved_path).expanduser().resolve()
    workspace_root = resolve_workspace_path(session.workspace)
    if workspace_root != target and workspace_root not in target.parents:
        raise HTTPException(status_code=403, detail="路径不在工作区内")
    return session, target, resolved_path


def launch_editor_process(*, editor: str, target: Path) -> list[str]:
    normalized_editor = editor.strip()
    if normalized_editor not in SUPPORTED_EDITOR_COMMANDS:
        raise HTTPException(status_code=400, detail=f"不支持的编辑器命令：{normalized_editor}")

    executable = shutil.which(normalized_editor)
    if not executable:
        raise HTTPException(status_code=404, detail=f"未找到编辑器命令：{normalized_editor}")

    command = [executable, str(target)]
    if normalized_editor == "devenv":
        command = [executable, "/Edit", str(target)]

    popen_kwargs: dict[str, Any] = {
        "cwd": str(target if target.is_dir() else target.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(command, **popen_kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"未找到编辑器命令：{normalized_editor}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"启动编辑器失败：{exc}") from exc

    return command


def launch_file_manager_process(target: Path) -> list[str]:
    if sys.platform == "win32":
        executable = shutil.which("explorer") or "explorer"
        command = [executable, str(target)]
    elif sys.platform == "darwin":
        executable = shutil.which("open")
        if not executable:
            raise HTTPException(status_code=404, detail="未找到 open 命令")
        command = [executable, str(target)]
    else:
        executable = shutil.which("xdg-open") or shutil.which("gio")
        if not executable:
            raise HTTPException(status_code=404, detail="未找到 xdg-open 或 gio 命令")
        command = [executable, str(target)] if Path(executable).name != "gio" else [executable, "open", str(target)]

    popen_kwargs: dict[str, Any] = {
        "cwd": str(target),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(command, **popen_kwargs)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"打开文件资源管理器失败：{exc}") from exc
    return command


def register_file_routes(
    app: FastAPI,
    *,
    deps: FileRouteDeps,
) -> None:
    @app.get("/api/files")
    async def get_file(
        session_id: str = Query(...),
        path: str = Query(...),
    ) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        session.selected_file_path = normalize_relative_path(path, session.workspace)

        filename = Path(session.selected_file_path).name
        if filename not in session.open_files:
            session.open_files.append(filename)
        session.touch()

        return JSONResponse(
            {
                "selectedFilePath": session.selected_file_path,
                "selectedFileContent": read_text_file(session.selected_file_path, session.workspace),
                "openFiles": session.open_files[-6:],
            }
        )

    @app.get("/api/files/open")
    @app.post("/api/files/open")
    async def open_file_in_editor(
        session_id: str | None = Query(None),
        path: str | None = Query(None),
        editor: str | None = Query(None),
        body: dict[str, Any] | None = Body(None),
    ) -> JSONResponse:
        payload = body if isinstance(body, dict) else {}
        resolved_session_id = str(payload.get("session_id") or session_id or "").strip()
        resolved_path_arg = str(payload.get("path") or path or "").strip()
        resolved_editor = str(payload.get("editor") or editor or "").strip()

        if not resolved_session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")
        if not resolved_path_arg:
            raise HTTPException(status_code=400, detail="缺少 path")
        if not resolved_editor:
            raise HTTPException(status_code=400, detail="缺少 editor")

        session, target, resolved_path = resolve_workspace_target(
            resolved_session_id,
            resolved_path_arg,
            deps=deps,
        )
        if not target.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="目标不是文件")

        command = launch_editor_process(editor=resolved_editor, target=target)
        session.selected_file_path = resolved_path
        session.touch()
        return JSONResponse(
            {
                "launched": True,
                "path": resolved_path,
                "absolutePath": str(target),
                "editor": resolved_editor,
                "command": command,
            }
        )

    @app.post("/api/sessions/{session_id}/open-workspace")
    async def open_workspace(
        session_id: str,
        body: dict[str, Any] | None = Body(None),
    ) -> JSONResponse:
        payload = body if isinstance(body, dict) else {}
        target_kind = str(payload.get("target") or "editor").strip()
        editor = str(payload.get("editor") or "").strip()
        session = deps.session_registry.require_session(session_id)
        workspace_root = resolve_workspace_path(session.workspace)
        if not workspace_root.exists():
            raise HTTPException(status_code=404, detail="工作区不存在")
        if not workspace_root.is_dir():
            raise HTTPException(status_code=400, detail="工作区不是目录")

        if target_kind == "explorer":
            command = launch_file_manager_process(workspace_root)
            return JSONResponse(
                {
                    "launched": True,
                    "target": target_kind,
                    "absolutePath": str(workspace_root),
                    "command": command,
                }
            )

        if target_kind != "editor":
            raise HTTPException(status_code=400, detail=f"不支持的打开目标：{target_kind}")
        if not editor:
            raise HTTPException(status_code=400, detail="缺少 editor")

        command = launch_editor_process(editor=editor, target=workspace_root)
        return JSONResponse(
            {
                "launched": True,
                "target": target_kind,
                "absolutePath": str(workspace_root),
                "editor": editor,
                "command": command,
            }
        )

    @app.get("/api/sessions/{session_id}/preview")
    @app.get("/api/sessions/{session_id}/preview/{preview_path:path}")
    async def preview_session_file(session_id: str, preview_path: str = "") -> FileResponse:
        session = deps.session_registry.require_session(session_id)
        target = resolve_preview_path(preview_path, session.workspace)
        return FileResponse(target)

    @app.get("/api/files/preview")
    async def preview_workspace_file(
        session_id: str = Query(...),
        path: str = Query(...),
    ) -> FileResponse:
        _session, target, _resolved_path = resolve_workspace_target(
            session_id,
            path,
            deps=deps,
        )
        if not target.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        if not target.is_file():
            raise HTTPException(status_code=400, detail="目标不是文件")
        return FileResponse(target)

    @app.get("/api/preview/select-bridge.js")
    async def get_preview_select_bridge_script() -> Response:
        return Response(
            PREVIEW_SELECT_BRIDGE_SCRIPT,
            media_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/sessions/{session_id}/file-tree")
    async def get_file_tree(
        session_id: str,
        force: bool = Query(False),
        path: str | None = Query(None),
    ) -> JSONResponse:
        session = deps.session_registry.require_session(session_id)
        if path is not None and str(path).strip():
            try:
                directory = await asyncio.wait_for(
                    asyncio.to_thread(session.get_file_tree_directory, path, force),
                    timeout=15,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except asyncio.TimeoutError:
                directory = None
            return JSONResponse(
                {
                    "directory": directory,
                    "revision": session.file_tree_revision,
                }
            )
        try:
            tree = await asyncio.wait_for(asyncio.to_thread(session.get_file_tree, force), timeout=15)
        except asyncio.TimeoutError:
            tree = []
        return JSONResponse(
            {
                "fileTree": tree,
                "revision": session.file_tree_revision,
            },
        )

    @app.get("/api/sessions/{session_id}/file-tree/events")
    async def get_file_tree_events(
        session_id: str,
        since: int = Query(0),
    ) -> StreamingResponse:
        session = deps.session_registry.require_session(session_id)

        async def event_generator():
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            subscriber_id = session.subscribe_file_tree(queue)
            try:
                if session.can_replay_file_tree_events_since(since):
                    missed_events = session.file_tree_events_since(since)
                    for event in missed_events:
                        yield sse_data(event)
                else:
                    yield sse_data(session.file_tree_snapshot_event())

                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=25)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event is None:
                        break
                    yield sse_data(event)
            finally:
                session.unsubscribe_file_tree(subscriber_id)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.put("/api/files")
    async def save_file(
        session_id: str = Query(...),
        path: str = Query(...),
        body: dict | None = Body(None),
    ) -> JSONResponse:
        session, target, resolved_path = resolve_workspace_target(session_id, path, deps=deps)
        content = body.get("content", "") if body else ""
        try:
            existed_before_save = target.exists()
            before_text = read_text_file(str(target), session.workspace) if existed_before_save else ""
            ensure_code_change_baseline(session)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            session.mark_file_tree_dirty(paths=[target])
            code_change = None
            if (not existed_before_save) or before_text != content:
                code_change = record_code_change(
                    session,
                    action="added" if not existed_before_save else "modified",
                    path=target,
                    before_text=before_text,
                    after_text=content,
                    source="editor",
                    summary=f"{'手动新增' if not existed_before_save else '手动保存'} {relative_workspace_path(target, session.workspace)}",
                )
                schedule_workspace_rag_index(APP_DATA_ROOT, session.workspace)
            session.touch()
            return JSONResponse({"saved": True, "path": resolved_path, "codeChange": code_change})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
