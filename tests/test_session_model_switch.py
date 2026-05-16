import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coding_agent.tools import InteractiveCommandSession
from fastapi_app import main as api_main


class SwitchSessionModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-session-switch-")).resolve()
        self.interactive_session = InteractiveCommandSession(workspace=self.workspace)
        self.session = api_main.UISession(
            session_id="session-123",
            model="Demo",
            workspace=str(self.workspace),
            interactive_command_session=self.interactive_session,
        )
        api_main._sessions[self.session.session_id] = self.session

    def tearDown(self) -> None:
        api_main._sessions.pop(self.session.session_id, None)
        self.interactive_session.close()

    async def test_switch_session_model_preserves_runtime_metadata(self) -> None:
        dummy_config = type("DummyConfig", (), {"model": "gpt-test", "max_steps": 6})()

        with (
            patch.object(api_main, "resolve_model_option", return_value={"envFile": ".env"}),
            patch.object(api_main.AgentLLMConfig, "from_env", return_value=dummy_config),
            patch.object(api_main, "OpenAICompatibleClient", return_value=object()),
            patch.object(api_main, "CodingPromptBrain", return_value=object()),
        ):
            await api_main.switch_session_model(
                self.session.session_id,
                api_main.SwitchModelRequest(model="gpt-test"),
            )

        self.assertIsNotNone(self.session.chat_session)
        metadata = self.session.chat_session.agent.tool_context_metadata
        self.assertEqual(metadata["session_id"], self.session.session_id)
        self.assertEqual(metadata["backend_base_url"], api_main.BACKEND_BASE_URL)
        self.assertIs(metadata["interactive_command_session"], self.interactive_session)


if __name__ == "__main__":
    unittest.main()
