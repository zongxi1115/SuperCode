import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import ChatSession
from fastapi_app import main as api_main


class MessageRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-routing-")).resolve()

    def test_route_agent_type_uses_deploy_keywords_per_message(self) -> None:
        session = api_main.UISession(
            session_id="routing-1",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="coding",
        )

        routed = api_main.route_agent_type_for_message(session, "帮我部署上线到生产环境")

        self.assertEqual(routed, "deploy")

    def test_route_agent_type_uses_transfer_keywords_per_message(self) -> None:
        session = api_main.UISession(
            session_id="routing-1b",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="coding",
        )

        routed = api_main.route_agent_type_for_message(session, "把这些文件上传到服务器")

        self.assertEqual(routed, "deploy")

    def test_route_agent_type_prefers_coding_for_explicit_code_change(self) -> None:
        session = api_main.UISession(
            session_id="routing-2",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="deploy",
            deploy_state={
                "active_session_id": "deploy-1",
                "active_root_path": str(self.workspace),
            },
        )

        routed = api_main.route_agent_type_for_message(session, "修改一下部署脚本并补测试")

        self.assertEqual(routed, "coding")

    def test_route_agent_type_keeps_generic_follow_up_on_active_deploy_context(self) -> None:
        manager = api_main.DeployConnectionManager(self.workspace)
        connection = manager.create_connection(str(self.workspace), "prod", "test")
        session = api_main.UISession(
            session_id="routing-3",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="deploy",
            deploy_connection_manager=manager,
            deploy_state={
                "active_session_id": connection["session_id"],
                "active_root_path": str(self.workspace),
            },
        )

        routed = api_main.route_agent_type_for_message(session, "继续")

        self.assertEqual(routed, "deploy")

    def test_route_session_for_user_message_rebuilds_agent_type_per_message(self) -> None:
        session = api_main.UISession(
            session_id="routing-4",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="coding",
            chat_session=ChatSession(agent=object()),
        )

        with patch.object(
            api_main,
            "build_chat_session",
            return_value=(ChatSession(agent=object()), "Demo", None, None),
        ) as mock_build:
            api_main.route_session_for_user_message(session, "帮我部署到 Vercel")

        self.assertEqual(session.agent_type, "deploy")
        self.assertEqual(session.phase, "idle")
        self.assertEqual(session.plan_steps[0]["title"], "连接部署目标")
        mock_build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
