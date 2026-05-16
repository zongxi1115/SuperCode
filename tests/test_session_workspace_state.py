import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi_app import main as api_main


class _FakeTerminalRuntime:
    def snapshot(self, session_id: str) -> api_main.TerminalSnapshotResponse:
        return api_main.TerminalSnapshotResponse(
            sessionId=session_id,
            output="terminal output",
            revision=3,
            isAlive=True,
            shell="powershell",
        )


class _FakeInteractiveCommandSession:
    def list_managed_processes(self, only_active: bool = True) -> list[dict[str, object]]:
        return [
            {
                "terminalId": "terminal-1",
                "command": "pnpm dev",
                "rootPid": 123,
                "status": "running",
                "returnCode": None,
                "startedAt": 1,
                "terminatedAt": None,
                "processCount": 1,
                "processes": [],
            }
        ]


class SessionWorkspaceStateTests(unittest.TestCase):
    def test_file_tree_is_cached_until_marked_dirty(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-tree-cache-")).resolve()
        session = api_main.UISession(
            session_id="session-tree-cache",
            model="test-model",
            workspace=str(workspace),
        )
        first_tree = [{"path": str(workspace), "name": "first", "type": "folder", "children": []}]
        second_tree = [{"path": str(workspace), "name": "second", "type": "folder", "children": []}]

        with mock.patch.object(api_main, "build_file_tree", side_effect=[first_tree, second_tree]) as mocked_build:
            self.assertEqual(session.get_file_tree(), first_tree)
            self.assertEqual(session.get_file_tree(), first_tree)
            self.assertEqual(mocked_build.call_count, 1)

            session.mark_file_tree_dirty()

            self.assertEqual(session.get_file_tree(), second_tree)
            self.assertEqual(mocked_build.call_count, 2)

    def test_terminal_snapshot_can_merge_file_tree_and_processes(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-terminal-state-")).resolve()
        session = api_main.UISession(
            session_id="session-terminal-state",
            model="test-model",
            workspace=str(workspace),
            terminal_runtime=_FakeTerminalRuntime(),
            interactive_command_session=_FakeInteractiveCommandSession(),
        )
        tree = [{"path": str(workspace), "name": workspace.name, "type": "folder", "children": []}]

        with mock.patch.object(api_main, "build_file_tree", return_value=tree):
            snapshot = session.terminal_snapshot(include_file_tree=True, include_processes=True)

        self.assertEqual(snapshot.output, "terminal output")
        self.assertEqual(snapshot.fileTree, tree)
        self.assertEqual(snapshot.processes, session.get_managed_processes())


if __name__ == "__main__":
    unittest.main()
