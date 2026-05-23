import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import ChatSession, StepRecord, ToolCall, ToolResult
from agent.tools import ToolContext
from fastapi_app import main as api_main
from fastapi_app.api_models import PlanDraftUpdateRequest, PlanSubmitRequest, ToolInputSubmitRequest
from plan_agent.brain import PlanPromptBrain
from plan_agent.tools import AskPlanQuestionsTool, ReadCurrentPlanTool, SavePlanTool, SearchWebTool


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return self.payload


class PlanAgentToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-plan-tools-")).resolve()
        (self.workspace / ".env").write_text("SC_TINYFISH_API_KEY=test-key\n", encoding="utf-8")
        self.context = ToolContext(
            workspace=self.workspace,
            metadata={"project_root": str(self.workspace)},
        )

    def test_ask_plan_questions_tool_returns_supported_schema(self) -> None:
        output = AskPlanQuestionsTool().run(
            {
                "title": "确认需求",
                "questions": [
                    {
                        "id": "platform",
                        "type": "single_choice",
                        "prompt": "首发平台是什么？",
                        "options": [
                            {"label": "Web"},
                            {"label": "桌面端"},
                        ],
                    }
                ],
            },
            self.context,
        )

        self.assertTrue(output["requires_user_input"])
        self.assertEqual(output["input_kind"], "plan_questions")
        self.assertEqual(output["questions"][0]["id"], "platform")
        self.assertEqual(output["questions"][0]["options"][0]["id"], "web")
        self.assertEqual(output["data_parts"][0]["type"], "data-plan-questions")

    def test_save_plan_tool_returns_structured_plan_draft(self) -> None:
        output = SavePlanTool().run(
            {
                "title": "后台 MVP",
                "summary": "先做登录和仪表盘",
                "overview": "先完成最小可用后台闭环，再补扩展能力。",
                "key_steps": ["搭登录页", "接鉴权", "做仪表盘"],
                "markdown": "## 步骤\n- 登录\n- 仪表盘",
            },
            self.context,
        )

        self.assertEqual(output["plan"]["title"], "后台 MVP")
        self.assertEqual(output["plan"]["summary"], "先做登录和仪表盘")
        self.assertEqual(output["plan"]["overview"], "先完成最小可用后台闭环，再补扩展能力。")
        self.assertEqual(output["plan"]["keySteps"], ["搭登录页", "接鉴权", "做仪表盘"])
        self.assertEqual(set(output["plan"].keys()), {"title", "summary", "overview", "keySteps", "markdown"})
        self.assertEqual(output["data_parts"][0]["type"], "data-plan-draft")

    def test_save_plan_tool_generates_markdown_when_missing(self) -> None:
        output = SavePlanTool().run(
            {
                "title": "后台 MVP",
                "summary": "先做登录和仪表盘",
                "overview": "先完成最小可用后台闭环，再补扩展能力。",
                "key_steps": ["搭登录页", "接鉴权", "做仪表盘"],
            },
            self.context,
        )

        markdown = output["plan"]["markdown"]
        self.assertIn("# 后台 MVP", markdown)
        self.assertIn("## 总览", markdown)
        self.assertIn("1. 搭登录页", markdown)

    def test_search_web_tool_parses_tinyfish_results(self) -> None:
        tool = SearchWebTool()
        with patch("plan_agent.tools.urlopen", return_value=_FakeHTTPResponse({
            "results": [
                {
                    "title": "Tinyfish Docs",
                    "url": "https://docs.tinyfish.ai",
                    "snippet": "Search docs",
                    "source": "tinyfish",
                }
            ]
        })):
            output = tool.run({"query": "tinyfish docs"}, self.context)

        self.assertEqual(output["count"], 1)
        self.assertEqual(output["results"][0]["title"], "Tinyfish Docs")
        self.assertEqual(output["results"][0]["url"], "https://docs.tinyfish.ai")

    def test_read_current_plan_tool_returns_latest_plan(self) -> None:
        tool = ReadCurrentPlanTool()
        context = ToolContext(
            workspace=self.workspace,
            metadata={
                "backend_base_url": "http://localhost:8000",
                "session_id": "session-1",
            },
        )
        with patch("plan_agent.tools.urlopen", return_value=_FakeHTTPResponse({
            "plan": {
                "title": "后台 MVP",
                "markdown": "# 后台 MVP\n\n- 登录",
            },
            "planState": {
                "status": "draft_ready",
            },
        })):
            output = tool.run({}, context)

        self.assertEqual(output["plan"]["title"], "后台 MVP")
        self.assertEqual(output["planState"]["status"], "draft_ready")


class PlanAgentEndpointsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp(prefix="supercode-plan-endpoint-")).resolve()
        self.session = api_main.UISession(
            session_id="plan-session",
            model="Demo",
            workspace=str(self.workspace),
            agent_type="plan",
            chat_session=ChatSession(agent=object()),
            plan_state={
                "status": "draft_ready",
                "draft": {
                    "title": "后台 MVP",
                    "summary": "先做登录和仪表盘",
                    "overview": "先完成最小可用后台闭环，再补扩展能力。",
                    "keySteps": ["搭登录页", "接鉴权", "做仪表盘"],
                    "markdown": "## 步骤\n- 登录\n- 仪表盘",
                },
            },
        )
        self.session.pending_user_input_requests["tool-plan-1"] = {
            "assistant_id": "assistant-1",
            "tool_name": "ask_plan_questions",
            "request": {
                "id": "tool-plan-1",
                "kind": "plan_questions",
                "title": "确认需求",
                "questions": [
                    {
                        "id": "platform",
                        "type": "single_choice",
                        "prompt": "首发平台是什么？",
                        "required": True,
                        "options": [
                            {"id": "web", "label": "Web"},
                            {"id": "desktop", "label": "桌面端"},
                        ],
                    },
                    {
                        "id": "brand",
                        "type": "short_text",
                        "prompt": "品牌名是什么？",
                        "required": True,
                    },
                ],
            },
        }
        self.session.chat_session.state.current_input = "先帮我规划后台 MVP"
        self.session.chat_session.state.data["turn_index"] = 1
        self.session.chat_session.state.data["step_records"] = [
            StepRecord(
                turn_index=1,
                index=1,
                thought="需求还缺两个关键输入，先提问。",
                tool_call=ToolCall(
                    id="tool-plan-1",
                    name="ask_plan_questions",
                    arguments={
                        "title": "确认需求",
                        "questions": self.session.pending_user_input_requests["tool-plan-1"]["request"]["questions"],
                    },
                ),
                tool_result=ToolResult(
                    name="ask_plan_questions",
                    tool_call_id="tool-plan-1",
                    output={
                        "requires_user_input": True,
                        "input_kind": "plan_questions",
                        "questions": self.session.pending_user_input_requests["tool-plan-1"]["request"]["questions"],
                    },
                    success=True,
                ),
            )
        ]
        api_main._sessions[self.session.session_id] = self.session

    async def asyncTearDown(self) -> None:
        api_main._sessions.pop(self.session.session_id, None)

    async def test_submit_tool_input_updates_history_and_returns_continue_hint(self) -> None:
        response = await api_main.submit_tool_input(
            self.session.session_id,
            "tool-plan-1",
            ToolInputSubmitRequest(
                answers=[
                    {
                        "questionId": "platform",
                        "selectedOptionIds": ["web"],
                    },
                    {
                        "questionId": "brand",
                        "text": "SuperCode",
                    },
                ]
            ),
        )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertTrue(payload["shouldContinue"])
        self.assertEqual(payload["assistantId"], "assistant-1")
        self.assertEqual(payload["phase"], "clarifying")
        self.assertEqual(self.session.history_tools[0]["name"], "ask_plan_questions")
        answers = self.session.history_tools[0]["output"]["answers"]
        self.assertEqual(answers[0]["selectedOptions"][0]["label"], "Web")
        self.assertEqual(answers[1]["text"], "SuperCode")

    async def test_submit_tool_input_records_answers_as_original_tool_result(self) -> None:
        await api_main.submit_tool_input(
            self.session.session_id,
            "tool-plan-1",
            ToolInputSubmitRequest(
                answers=[
                    {
                        "questionId": "platform",
                        "selectedOptionIds": ["web"],
                    },
                    {
                        "questionId": "brand",
                        "text": "SuperCode",
                    },
                ]
            ),
        )

        step = self.session.chat_session.state.data["step_records"][0]
        tool_result = step.tool_result
        self.assertIsNotNone(tool_result)
        self.assertEqual(tool_result.tool_call_id, "tool-plan-1")
        self.assertFalse(tool_result.output.get("requires_user_input", False))
        self.assertEqual(tool_result.output["answers"][1]["text"], "SuperCode")

        brain = PlanPromptBrain(client=object())
        native_messages = brain._build_current_turn_native_messages(self.session.chat_session.state)
        self.assertEqual(native_messages[-1]["role"], "tool")
        self.assertEqual(native_messages[-1]["tool_call_id"], "tool-plan-1")
        self.assertIn("SuperCode", native_messages[-1]["content"])
        self.assertNotIn("requires_user_input", native_messages[-1]["content"])

    async def test_submit_plan_switches_session_to_coding_and_clears_history(self) -> None:
        self.session.history_messages = [{"id": "u1", "role": "user", "content": "先帮我规划"}]
        self.session.history_tools = [{"id": "tool-1", "name": "save_plan", "state": "completed"}]
        self.session.thoughts = ["先调研"]

        with patch.object(
            api_main,
            "build_chat_session",
            return_value=(ChatSession(agent=object()), "Demo", None, None, None),
        ):
            response = await api_main.submit_plan(
                self.session.session_id,
                PlanSubmitRequest(),
            )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["agentType"], "coding")
        self.assertTrue(payload["shouldStartCoding"])
        self.assertEqual(self.session.agent_type, "coding")
        self.assertEqual(self.session.history_messages, [])
        self.assertEqual(self.session.history_tools, [])
        self.assertEqual(self.session.thoughts, [])
        self.assertIn("后台 MVP", payload["codingInput"])
        self.assertIn("总览", payload["codingInput"])
        self.assertIn("关键步骤", payload["codingInput"])
        self.assertIn("仪表盘", payload["codingInput"])

    async def test_save_current_plan_draft_updates_session_plan_state(self) -> None:
        response = await api_main.save_current_plan_draft(
            self.session.session_id,
            PlanDraftUpdateRequest(
                title="后台 MVP v2",
                markdown="# 后台 MVP v2\n\n## 新计划\n\n- 登录\n- 仪表盘\n- 审计日志",
            ),
        )

        payload = json.loads(response.body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["plan"]["title"], "后台 MVP v2")
        self.assertIn("审计日志", payload["plan"]["markdown"])
        self.assertEqual(self.session.plan_state["draft"]["title"], "后台 MVP v2")
        self.assertEqual(self.session.plan_state["status"], "awaiting_user_input")


if __name__ == "__main__":
    unittest.main()
