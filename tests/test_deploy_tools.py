import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import ChatSession
from agent.tools import ToolContext
import deploy_agent.tools as deploy_tools_module
from deploy_agent.tools import (
    ConnectTool,
    DeployConnectionManager,
    DeployExecuteTool,
    DeployListFilesTool,
    DeployReadFileTool,
    DeployTransferFilesTool,
)
from fastapi_app import main as api_main
from fastapi_app.api_models import ConnectToolSubmitRequest


class _FakeRemoteChannel:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", exit_code: int = 0) -> None:
        self.stdout_chunks = [stdout] if stdout else []
        self.stderr_chunks = [stderr] if stderr else []
        self.exit_code = exit_code
        self.executed_command: str | None = None

    def settimeout(self, timeout: int) -> None:  # noqa: ARG002
        return None

    def exec_command(self, command: str) -> None:
        self.executed_command = command

    def recv_ready(self) -> bool:
        return bool(self.stdout_chunks)

    def recv(self, size: int) -> bytes:  # noqa: ARG002
        return self.stdout_chunks.pop(0)

    def recv_stderr_ready(self) -> bool:
        return bool(self.stderr_chunks)

    def recv_stderr(self, size: int) -> bytes:  # noqa: ARG002
        return self.stderr_chunks.pop(0)

    def exit_status_ready(self) -> bool:
        return self.executed_command is not None and not self.stdout_chunks and not self.stderr_chunks

    def recv_exit_status(self) -> int:
        return self.exit_code

    def close(self) -> None:
        return None


class _FakeRemoteTransport:
    def __init__(self, channel: _FakeRemoteChannel) -> None:
        self.channel = channel

    def open_session(self) -> _FakeRemoteChannel:
        return self.channel


class _FakeRemoteAttr:
    def __init__(self, filename: str, is_dir: bool) -> None:
        self.filename = filename
        self.st_mode = stat.S_IFDIR if is_dir else stat.S_IFREG


class _FakeRemoteSFTP:
    def __init__(self) -> None:
        self.stats: dict[str, _FakeRemoteAttr] = {
            "/srv/app": _FakeRemoteAttr("app", True),
        }
        self.created_dirs: list[str] = []
        self.put_calls: list[tuple[str, str]] = []

    def stat(self, path: str) -> _FakeRemoteAttr:
        attr = self.stats.get(path)
        if attr is None:
            raise FileNotFoundError(path)
        return attr

    def mkdir(self, path: str) -> None:
        self.created_dirs.append(path)
        self.stats[path] = _FakeRemoteAttr(Path(path).name or path, True)

    def put(self, local_path: str, remote_path: str) -> None:
        self.put_calls.append((local_path, remote_path))
        self.stats[remote_path] = _FakeRemoteAttr(Path(remote_path).name, False)

    def close(self) -> None:
        return None


class _FakeRemoteSSHClient:
    def __init__(self, channel: _FakeRemoteChannel | None = None, sftp: _FakeRemoteSFTP | None = None) -> None:
        self.channel = channel or _FakeRemoteChannel()
        self.sftp = sftp or _FakeRemoteSFTP()
        self.connected_kwargs: dict[str, object] | None = None
        self.policy: object | None = None

    def set_missing_host_key_policy(self, policy: object) -> None:
        self.policy = policy

    def connect(self, **kwargs: object) -> None:
        self.connected_kwargs = kwargs

    def get_transport(self) -> _FakeRemoteTransport:
        return _FakeRemoteTransport(self.channel)

    def open_sftp(self) -> _FakeRemoteSFTP:
        return self.sftp

    def close(self) -> None:
        return None


class DeployToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-deploy-tools-")).resolve()
        self.deploy_root = self.workspace / "deploy-root"
        self.deploy_root.mkdir()
        (self.deploy_root / "app").mkdir()
        (self.deploy_root / "app" / "config.json").write_text('{"name":"demo"}\n', encoding="utf-8")
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (self.workspace / "README.deploy.md").write_text("# deploy\n", encoding="utf-8")
        self.manager = DeployConnectionManager(self.workspace)
        connection = self.manager.create_connection(str(self.deploy_root), "deploy-root", "test")
        self.deploy_session_id = str(connection["session_id"])
        self.context = ToolContext(
            workspace=self.workspace,
            metadata={"deploy_connection_manager": self.manager},
        )

    def test_connect_requests_user_input(self) -> None:
        output = ConnectTool().run({}, self.context)

        self.assertTrue(output["requires_user_input"])
        self.assertEqual(output["input_kind"], "deploy_connect")
        field_names = [f["name"] for f in output["fields"]]
        self.assertIn("host", field_names)
        self.assertIn("username", field_names)
        self.assertIn("password", field_names)
        self.assertIn("root_path", field_names)
        self.assertIn("extra_info", field_names)

    def test_list_files_renders_tree_inside_connection_root(self) -> None:
        output = DeployListFilesTool().run(
            {"session_id": self.deploy_session_id, "path": "."},
            self.context,
        )

        self.assertIn("# Session: ", output)
        self.assertIn("app/", output)
        self.assertIn("app/config.json", output)

    def test_read_file_returns_numbered_lines(self) -> None:
        output = DeployReadFileTool().run(
            {"session_id": self.deploy_session_id, "path": "app/config.json"},
            self.context,
        )

        self.assertIn("# File: app/config.json", output)
        self.assertIn("# Total lines: 1", output)
        self.assertIn('1 | {"name":"demo"}', output)

    def test_execute_runs_command_in_requested_cwd(self) -> None:
        output = DeployExecuteTool().run(
            {
                "session_id": self.deploy_session_id,
                "cwd": "app",
                "command": 'python -c "import os; print(os.path.basename(os.getcwd()))"',
                "timeout": 10,
            },
            self.context,
        )

        self.assertIn("exit_code: 0", output)
        self.assertIn("stdout:", output)
        self.assertIn("app", output)

    def test_transfer_files_accepts_path_and_file_arrays(self) -> None:
        output = DeployTransferFilesTool().run(
            {
                "session_id": self.deploy_session_id,
                "path": ["src"],
                "file": ["README.deploy.md"],
                "target_dir": "bundle",
            },
            self.context,
        )

        self.assertEqual(output["count"], 2)
        self.assertTrue((self.deploy_root / "bundle" / "src" / "main.py").exists())
        self.assertTrue((self.deploy_root / "bundle" / "README.deploy.md").exists())
        transferred_sources = {item["source"] for item in output["transferred"]}
        self.assertEqual(transferred_sources, {"src", "README.deploy.md"})

    def test_remote_execute_uses_ssh_instead_of_local_subprocess(self) -> None:
        remote_connection = self.manager.create_connection(
            root_path="/srv/app",
            display_name="remote-prod",
            description="remote",
            host="example.com",
            username="root",
            password="secret",
        )
        remote_session_id = str(remote_connection["session_id"])
        fake_client = _FakeRemoteSSHClient(channel=_FakeRemoteChannel(stdout=b"remote-ok\n"))
        fake_paramiko = SimpleNamespace(
            SSHClient=lambda: fake_client,
            AutoAddPolicy=lambda: object(),
        )

        with (
            patch.object(deploy_tools_module, "paramiko", fake_paramiko),
            patch.object(deploy_tools_module.subprocess, "Popen", side_effect=AssertionError("不应走本地 subprocess")),
        ):
            output = DeployExecuteTool().run(
                {
                    "session_id": remote_session_id,
                    "cwd": ".",
                    "command": "pwd",
                    "timeout": 10,
                },
                self.context,
            )

        self.assertIn("remote_host: example.com", output)
        self.assertIn("stdout:", output)
        self.assertIn("remote-ok", output)
        self.assertEqual(fake_client.connected_kwargs["hostname"], "example.com")
        self.assertEqual(fake_client.connected_kwargs["username"], "root")
        self.assertEqual(fake_client.channel.executed_command, "cd /srv/app && pwd")
        self.assertNotIn("secret", str(self.manager.export_state()))

    def test_remote_connection_rejects_windows_style_root_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "Linux 服务器上的绝对路径"):
            self.manager.create_connection(
                root_path=r"D:\vibe_projs\superdocs_test\516",
                display_name="remote-prod",
                description="remote",
                host="example.com",
                username="root",
                password="secret",
            )

    def test_remote_transfer_files_uses_sftp_put(self) -> None:
        remote_connection = self.manager.create_connection(
            root_path="/srv/app",
            display_name="remote-prod",
            description="remote",
            host="example.com",
            username="root",
            password="secret",
        )
        remote_session_id = str(remote_connection["session_id"])
        fake_sftp = _FakeRemoteSFTP()
        fake_client = _FakeRemoteSSHClient(sftp=fake_sftp)
        fake_paramiko = SimpleNamespace(
            SSHClient=lambda: fake_client,
            AutoAddPolicy=lambda: object(),
        )

        with patch.object(deploy_tools_module, "paramiko", fake_paramiko):
            output = DeployTransferFilesTool().run(
                {
                    "session_id": remote_session_id,
                    "file": "README.deploy.md",
                    "target_dir": "bundle",
                },
                self.context,
            )

        self.assertEqual(output["count"], 1)
        self.assertEqual(output["transferred"][0]["destination"], "bundle/README.deploy.md")
        self.assertEqual(len(fake_sftp.put_calls), 1)
        self.assertEqual(fake_sftp.put_calls[0][1], "/srv/app/bundle/README.deploy.md")


class DeployConnectEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-deploy-endpoint-")).resolve()
        self.session = api_main.UISession(
            session_id="deploy-session",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="deploy",
            chat_session=ChatSession(agent=object()),
        )
        self.session.pending_connect_requests["tool-connect-1"] = {
            "assistant_id": "assistant-1",
            "tool_name": "connect",
            "request": {
                "id": "tool-connect-1",
                "kind": "deploy_connect",
                "fields": [{"name": "root_path", "required": True}],
            },
        }
        api_main._sessions[self.session.session_id] = self.session

    async def asyncTearDown(self) -> None:
        api_main._sessions.pop(self.session.session_id, None)

    async def test_submit_connect_tool_creates_connection_and_updates_history(self) -> None:
        response = await api_main.submit_connect_tool(
            self.session.session_id,
            "tool-connect-1",
            ConnectToolSubmitRequest(
                values={
                    "root_path": str(self.workspace),
                    "display_name": "production",
                    "description": "release workspace",
                    "extra_info": "domain=example.com; nginx=/etc/nginx/sites-enabled/example.conf",
                }
            ),
        )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertTrue(payload["shouldContinue"])
        self.assertEqual(payload["assistantId"], "assistant-1")
        self.assertEqual(payload["phase"], "connected")
        self.assertEqual(payload["deployState"]["active_display_name"], "production")
        self.assertEqual(
            payload["deployState"]["active_extra_info"],
            "domain=example.com; nginx=/etc/nginx/sites-enabled/example.conf",
        )
        self.assertEqual(len(self.session.deploy_connection_manager.list_connections()), 1)
        self.assertEqual(self.session.history_tools[0]["name"], "connect")
        self.assertEqual(
            self.session.history_tools[0]["output"]["display_name"],
            "production",
        )
        self.assertNotIn("password", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(self.session.phase, "connected")
        self.assertEqual(
            self.session.deploy_state["active_display_name"],
            "production",
        )
        self.assertEqual(
            self.session.deploy_state["active_extra_info"],
            "domain=example.com; nginx=/etc/nginx/sites-enabled/example.conf",
        )
        self.assertIsNotNone(self.session.deploy_state["active_session_id"])
        self.assertNotIn("tool-connect-1", self.session.pending_connect_requests)


if __name__ == "__main__":
    unittest.main()
