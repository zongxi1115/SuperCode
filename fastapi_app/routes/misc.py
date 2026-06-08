from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse


@dataclass(frozen=True)
class MiscRouteDeps:
    normalize_workspace: Callable[[str | None], str]
    list_child_directories: Callable[[str], list[str]]


def register_misc_routes(
    app: FastAPI,
    *,
    deps: MiscRouteDeps,
) -> None:
    @app.get("/scalar", include_in_schema=False)
    def scalar_docs():
        return HTMLResponse("""
<!doctype html>
<html>
  <head>
    <title>SuperCode API Docs</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/openapi.json"
      src="https://cdn.jsdelivr.net/npm/@scalar/api-reference">
    </script>
  </body>
</html>
""")

    @app.get("/api/health")
    async def health_check() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/api/directories")
    async def get_directories(path: str = Query(...)) -> JSONResponse:
        root = deps.normalize_workspace(path)
        return JSONResponse({"path": str(root), "children": deps.list_child_directories(root)})
