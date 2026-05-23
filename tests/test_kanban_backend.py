import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException

from fastapi_app import main as api_main
from fastapi_app.kanban_store import KanbanStore


class KanbanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = str(Path(tempfile.mkdtemp(prefix="supercode-kanban-workspace-")).resolve())
        self.store = KanbanStore(Path(tempfile.mkdtemp(prefix="supercode-kanban-store-")) / "state.sqlite3")

    def test_create_board_seeds_default_columns(self) -> None:
        board = self.store.create_board(self.workspace, "产品看板")

        self.assertEqual(board["name"], "产品看板")
        self.assertEqual([column["name"] for column in board["columns"]], ["Backlog", "Todo", "In Progress", "Done"])
        self.assertEqual(board["cards"], [])

    def test_card_crud_and_cross_column_reorder(self) -> None:
        board = self.store.create_board(self.workspace, "产品看板")
        backlog = next(column for column in board["columns"] if column["name"] == "Backlog")
        done = next(column for column in board["columns"] if column["name"] == "Done")

        first = self.store.create_card(
            self.workspace,
            board_id=board["id"],
            column_id=backlog["id"],
            title="设计插件接口",
            priority="high",
            labels=["backend", "api"],
        )
        second = self.store.create_card(
            self.workspace,
            board_id=board["id"],
            column_id=backlog["id"],
            title="补充测试",
        )

        self.assertEqual(first["status"], "Backlog")
        self.assertEqual(first["priority"], "high")
        self.assertEqual(first["labels"], ["backend", "api"])

        moved = self.store.update_card(
            self.workspace,
            first["id"],
            status="Done",
            priority="urgent",
            assignee="Alice",
        )
        self.assertEqual(moved["columnId"], done["id"])
        self.assertEqual(moved["status"], "Done")
        self.assertEqual(moved["priority"], "urgent")
        self.assertEqual(moved["assignee"], "Alice")

        reordered = self.store.reorder_cards(
            self.workspace,
            board_id=board["id"],
            target_column_id=done["id"],
            ordered_card_ids=[second["id"], first["id"]],
        )
        done_cards = [card for card in reordered["cards"] if card["columnId"] == done["id"]]
        self.assertEqual([card["id"] for card in done_cards], [second["id"], first["id"]])
        self.assertEqual([card["position"] for card in done_cards], [0.0, 1.0])

        result = self.store.delete_card(self.workspace, first["id"])
        self.assertTrue(result["deleted"])
        remaining = self.store.get_board(self.workspace, board["id"])
        self.assertNotIn(first["id"], [card["id"] for card in remaining["cards"]])

    def test_invalid_priority_is_rejected(self) -> None:
        board = self.store.create_board(self.workspace, "产品看板")

        with self.assertRaises(HTTPException) as raised:
            self.store.create_card(
                self.workspace,
                board_id=board["id"],
                title="非法优先级",
                priority="highest",
            )

        self.assertEqual(raised.exception.status_code, 400)


class KanbanEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.workspace = str(Path(tempfile.mkdtemp(prefix="supercode-kanban-api-")).resolve())
        self.workspace_id = quote(self.workspace, safe="")

    async def test_plugins_endpoint_includes_kanban(self) -> None:
        response = await api_main.get_plugins()
        plugins = response.body.decode("utf-8")

        self.assertIn('"id":"kanban"', plugins)
        self.assertIn("工作区级任务看板", plugins)

    async def test_kanban_endpoints_round_trip_workspace_board_and_card(self) -> None:
        board_response = await api_main.create_kanban_board(
            self.workspace_id,
            api_main.KanbanBoardCreateRequest(name="项目看板"),
        )
        board_payload = board_response.body.decode("utf-8")
        self.assertIn("项目看板", board_payload)

        boards_response = await api_main.list_kanban_boards(self.workspace_id)
        self.assertIn("项目看板", boards_response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
