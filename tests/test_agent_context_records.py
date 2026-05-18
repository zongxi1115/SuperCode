import unittest

from agent import BrainDecision, ChatSession, CodingAgent
from agent.schema import (
    AgentResponse,
    AgentState,
    ConversationMessage,
    StepRecord,
    ToolCall,
    ToolResult,
)
from agent.tools import BaseTool
from coding_agent.brain import CodingPromptBrain
from fastapi_app.session_history import seed_chat_session_history


class _NoopTool(BaseTool):
    name = "write_file"
    description = "创建文件"

    def run(self, arguments, context):  # noqa: ANN001
        return "已创建文件: demo.py"


class _OneShotBrain:
    def decide(self, state, tool_definitions, on_stream=None):  # noqa: ANN001
        return BrainDecision.finish(thought="完成", final_answer="done")


class _ToolResponseAgent:
    def run_turn(self, state: AgentState, on_event=None, continue_existing_turn=False):  # noqa: ANN001
        return AgentResponse(
            task=state.current_input,
            final_output="done",
            steps=[
                StepRecord(
                    turn_index=1,
                    index=1,
                    thought="创建文件",
                    tool_call=ToolCall(
                        id="step-1-tool-1-write_file",
                        name="write_file",
                        arguments={"filename": "demo.py", "content": "print('hi')"},
                    ),
                    tool_result=ToolResult(
                        name="write_file",
                        tool_call_id="step-1-tool-1-write_file",
                        output="已创建文件: demo.py",
                        success=True,
                    ),
                )
            ],
        )


class AgentContextRecordTests(unittest.TestCase):
    def test_chat_session_records_tools_without_appending_summary_message(self) -> None:
        session = ChatSession(agent=_ToolResponseAgent())

        response = session.ask("创建 demo.py")

        self.assertEqual(response.final_output, "done")
        self.assertEqual(
            [(message.role, message.content) for message in session.state.conversation_messages],
            [("user", "创建 demo.py"), ("assistant", "done")],
        )
        self.assertEqual(
            session.state.data["tool_records"][0]["arguments"],
            {"filename": "demo.py", "content": "print('hi')"},
        )
        self.assertEqual(session.state.data["planning_records"][0]["thought"], "创建文件")

    def test_seed_history_restores_tool_records_from_call_history(self) -> None:
        agent = CodingAgent(brain=_OneShotBrain(), tools=[_NoopTool()])
        session = ChatSession(agent=agent)

        seed_chat_session_history(
            session,
            history_messages=[
                {"id": "u1", "role": "user", "content": "创建 demo.py"},
                {
                    "id": "a1",
                    "role": "assistant",
                    "content": "done",
                    "thoughts": "已经决定创建 demo.py，不需要再重复规划。",
                    "toolCalls": [
                        {
                            "id": "tool-1",
                            "stepIndex": 1,
                            "name": "write_file",
                            "arguments": {"filename": "demo.py", "content": "print('hi')"},
                            "state": "completed",
                        }
                    ],
                },
            ],
            history_tools=[
                {
                    "id": "tool-1",
                    "name": "write_file",
                    "arguments": {"filename": "demo.py", "content": "print('hi')"},
                    "output": "已创建文件: demo.py",
                    "success": True,
                    "state": "completed",
                }
            ],
        )

        self.assertEqual(
            [(message.role, message.content) for message in session.state.conversation_messages],
            [("user", "创建 demo.py"), ("assistant", "done")],
        )
        self.assertEqual(session.state.data["tool_records"][0]["name"], "write_file")
        self.assertEqual(session.state.data["tool_records"][0]["output"], "已创建文件: demo.py")
        self.assertIn("创建 demo.py", session.state.data["planning_records"][0]["thought"])

    def test_coding_brain_places_tool_records_before_latest_user_message(self) -> None:
        brain = CodingPromptBrain(client=object())
        state = AgentState(task="task", current_input="继续")
        state.conversation_messages = [
            ConversationMessage(role="user", content="创建 demo.py"),
            ConversationMessage(role="assistant", content="done"),
            ConversationMessage(role="user", content="继续"),
        ]
        state.data["tool_records"] = [
            {
                "id": "tool-1",
                "name": "write_file",
                "arguments": {"filename": "demo.py", "content": "print('hi')"},
                "output": "已创建文件: demo.py",
                "success": True,
                "state": "completed",
            }
        ]
        state.data["planning_records"] = [
            {
                "id": "plan-1",
                "turn_index": 1,
                "step_index": 1,
                "thought": "方案已经确定：创建 demo.py，然后直接收尾。",
                "action": "tool",
                "tools": ["write_file"],
            }
        ]

        messages = brain._build_messages(
            state,
            tool_definitions={"write_file": {"description": "创建文件", "parameters_schema": None}},
            response_mode="native_tools",
        )

        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "继续")
        tool_record_message = messages[-2]["content"]
        self.assertIn("[内部工具调用记录]", tool_record_message)
        self.assertIn("write_file", tool_record_message)
        self.assertIn("demo.py", tool_record_message)
        self.assertNotIn("工具轨迹摘要", tool_record_message)
        planning_record_message = messages[-3]["content"]
        self.assertIn("[内部规划记录]", planning_record_message)
        self.assertIn("方案已经确定", planning_record_message)

    def test_coding_brain_includes_runtime_state_context_when_present(self) -> None:
        brain = CodingPromptBrain(client=object())
        state = AgentState(task="task", current_input="继续")
        state.conversation_messages = [
            ConversationMessage(role="user", content="检查部署"),
            ConversationMessage(role="assistant", content="好的"),
            ConversationMessage(role="user", content="继续"),
        ]
        state.data["runtime_state"] = {
            "agent_type": "deploy",
            "phase": "connected",
            "deploy_state": {
                "active_session_id": "deploy-1",
                "active_root_path": "D:/demo/app",
            },
        }

        messages = brain._build_messages(
            state,
            tool_definitions={},
            response_mode="native_tools",
        )

        self.assertEqual(messages[-1]["content"], "继续")
        runtime_state_message = messages[-2]["content"]
        self.assertIn("[内部会话状态]", runtime_state_message)
        self.assertIn("\"phase\": \"connected\"", runtime_state_message)
        self.assertIn("deploy-1", runtime_state_message)


if __name__ == "__main__":
    unittest.main()
