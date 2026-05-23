import json
import unittest

from agent.llm_client import CompletionResponse
from fastapi_app.agent_router import _build_route_messages, decide_agent_route_with_model


class _RouteClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.messages = []

    def chat_completion_messages(self, messages):  # noqa: ANN001
        self.messages = messages
        return CompletionResponse(text=self.text)


class AgentRouterTests(unittest.TestCase):
    def test_route_model_accepts_single_agent_name_output(self) -> None:
        client = _RouteClient("deploy")

        route_state = decide_agent_route_with_model(
            client,
            user_message="帮我部署上线",
            context={"currentAgentType": "coding"},
        )

        self.assertEqual(route_state["agentType"], "deploy")
        self.assertEqual(route_state["source"], "model")

    def test_route_prompt_uses_compact_context_without_message_roles(self) -> None:
        messages = _build_route_messages(
            "继续",
            {
                "currentAgentType": "coding",
                "phase": "idle",
                "pending": {"connectRequests": False, "planQuestions": False},
                "plan": {"status": "idle", "hasDraft": False, "hasSubmittedPlan": False},
                "deploy": {"hasActiveSession": False},
                "workspace": {"looksEmpty": False, "selectedFilePath": "app.py"},
                "recentMessages": [
                    {"role": "assistant", "content": "thinking", "reasoning": "hidden"},
                    {"role": "tool", "content": "tool output"},
                ],
                "recentUserMessages": ["上一轮需求"],
            },
        )

        self.assertEqual(len(messages), 2)
        self.assertIn("只输出一个词", str(messages[0]["content"]))
        self.assertNotIn("agentType", str(messages[0]["content"]))
        self.assertNotIn("confidence", str(messages[0]["content"]))
        payload = json.loads(str(messages[1]["content"]))

        self.assertEqual(payload["context"]["recentUser"], ["上一轮需求"])
        self.assertNotIn("recentMessages", payload["context"])
        self.assertNotIn("role", messages[1]["content"])
        self.assertNotIn("reasoning", messages[1]["content"])
        self.assertNotIn("tool output", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
