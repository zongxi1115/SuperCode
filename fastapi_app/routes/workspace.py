from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fastapi_app.api_models import (
    KanbanBoardCreateRequest,
    KanbanCardCreateRequest,
    KanbanCardReorderRequest,
    KanbanCardUpdateRequest,
)


@dataclass(frozen=True)
class WorkspaceRouteDeps:
    kanban_store: Any
    list_workspace_options: Callable[[], list[dict[str, str]]]
    normalize_workspace_identifier: Callable[[str], str]


def register_workspace_routes(
    app: FastAPI,
    *,
    deps: WorkspaceRouteDeps,
) -> None:
    @app.get("/api/workspaces")
    async def get_workspaces() -> JSONResponse:
        return JSONResponse({"workspaces": deps.list_workspace_options()})

    @app.get("/api/workspaces/{workspace_id:path}/kanban/boards")
    async def list_kanban_boards(workspace_id: str) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        boards = deps.kanban_store.list_boards(workspace)
        return JSONResponse({"boards": boards})

    @app.post("/api/workspaces/{workspace_id:path}/kanban/boards")
    async def create_kanban_board(
        workspace_id: str,
        request: KanbanBoardCreateRequest,
    ) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        board = deps.kanban_store.create_board(
            workspace,
            name=request.name,
            description=request.description,
        )
        return JSONResponse({"board": board})

    @app.get("/api/workspaces/{workspace_id:path}/kanban/boards/{board_id}")
    async def get_kanban_board(workspace_id: str, board_id: str) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        board = deps.kanban_store.get_board(workspace, board_id)
        return JSONResponse({"board": board})

    @app.post("/api/workspaces/{workspace_id:path}/kanban/cards")
    async def create_kanban_card(
        workspace_id: str,
        request: KanbanCardCreateRequest,
    ) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        card = deps.kanban_store.create_card(
            workspace,
            board_id=request.boardId,
            title=request.title,
            column_id=request.columnId,
            status=request.status,
            description=request.description,
            priority=request.priority,
            labels=request.labels,
            assignee=request.assignee,
        )
        board = deps.kanban_store.get_board(workspace, str(card["boardId"]))
        return JSONResponse({"card": card, "board": board})

    @app.patch("/api/workspaces/{workspace_id:path}/kanban/cards/{card_id}")
    async def update_kanban_card(
        workspace_id: str,
        card_id: str,
        request: KanbanCardUpdateRequest,
    ) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        provided_fields = set(getattr(request, "model_fields_set", set()))
        card = deps.kanban_store.update_card(
            workspace,
            card_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            labels=request.labels,
            assignee=request.assignee,
            column_id=request.columnId,
            status=request.status,
            position=request.position,
            ai_state=request.aiState if "aiState" in provided_fields else ...,
        )
        board = deps.kanban_store.get_board(workspace, str(card["boardId"]))
        return JSONResponse({"card": card, "board": board})

    @app.post("/api/workspaces/{workspace_id:path}/kanban/cards/reorder")
    async def reorder_kanban_cards(
        workspace_id: str,
        request: KanbanCardReorderRequest,
    ) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        board = deps.kanban_store.reorder_cards(
            workspace,
            board_id=request.boardId,
            card_id=request.cardId,
            column_id=request.columnId,
            target_column_id=request.targetColumnId,
            ordered_card_ids=request.orderedCardIds,
        )
        return JSONResponse({"board": board})

    @app.delete("/api/workspaces/{workspace_id:path}/kanban/cards/{card_id}")
    async def delete_kanban_card(workspace_id: str, card_id: str) -> JSONResponse:
        workspace = deps.normalize_workspace_identifier(workspace_id)
        result = deps.kanban_store.delete_card(workspace, card_id)
        return JSONResponse(result)
