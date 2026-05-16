import unittest

from agent.llm_client import CompletionResponse, CompletionToolCall, UnsupportedToolCallingError
from agent.llm_brain import OpenAICompatibleBrain
from agent.schema import AgentState


class ParseJsonOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brain = OpenAICompatibleBrain(client=object())

    def test_parse_single_json_object(self) -> None:
        payload = self.brain._parse_json_output(
            '{"action":"final","thought":"done","final_answer":"ok"}'
        )

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_parse_first_json_object_from_mixed_output(self) -> None:
        raw_output = """{"action":"tool","thought":"先写文件","tool_name":"write_file","tool_arguments":{"filename":"sudoku.py","content":"print(1)"}}\n</think>\n\n{"action":"final","thought":"结束","final_answer":"done"}"""

        payload = self.brain._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "tool")
        self.assertEqual(payload["tool_name"], "write_file")

    def test_parse_skips_non_decision_dicts(self) -> None:
        raw_output = """分析过程里先出现了一个普通对象 {"filename":"demo.py","content":"print(1)"}，真正的决策在后面 {"action":"final","thought":"结束","final_answer":"ok"}"""

        payload = self.brain._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_to_decision_can_infer_tool_action(self) -> None:
        decision = self.brain._to_decision(
            {
                "thought": "直接调用工具",
                "tool_name": "read_file",
                "tool_arguments": {"filename": "README.md"},
            }
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "read_file")

    def test_to_decision_can_infer_final_action(self) -> None:
        decision = self.brain._to_decision(
            {
                "thought": "直接结束",
                "final_answer": "done",
            }
        )

        self.assertEqual(decision.action, "final")
        self.assertEqual(decision.final_answer, "done")

    def test_to_decision_accepts_tool_and_args_aliases(self) -> None:
        decision = self.brain._to_decision(
            {
                "tool": "read_file",
                "args": {"filename": "README.md"},
            }
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "read_file")
        self.assertEqual(decision.tool_arguments, {"filename": "README.md"})

    def test_extracts_partial_write_file_content_for_realtime_tool_input(self) -> None:
        raw_output = (
            '{"action":"tool","tool_name":"write_file",'
            '"tool_arguments":{"filename":"demo.ts","content":"export const a = 1'
        )

        argument_name, streamed_input = self.brain._extract_partial_streamable_tool_input(
            raw_output,
            "write_file",
        )

        self.assertEqual(argument_name, "content")
        self.assertEqual(streamed_input, "export const a = 1")

    def test_extracts_only_new_content_for_replace_file_stream(self) -> None:
        old_only = (
            '{"action":"tool","tool_name":"replace_file",'
            '"tool_arguments":{"filename":"demo.ts","old_content":"before'
        )
        argument_name, streamed_input = self.brain._extract_partial_streamable_tool_input(
            old_only,
            "replace_file",
        )

        self.assertIsNone(argument_name)
        self.assertIsNone(streamed_input)

        with_new_content = (
            old_only
            + '","new_content":"after'
        )
        argument_name, streamed_input = self.brain._extract_partial_streamable_tool_input(
            with_new_content,
            "replace_file",
        )

        self.assertEqual(argument_name, "new_content")
        self.assertEqual(streamed_input, "after")

    def test_extracts_partial_apply_patch_content_for_realtime_tool_input(self) -> None:
        raw_output = (
            '{"action":"tool","tool_name":"apply_patch",'
            '"tool_arguments":{"patch":"*** Begin Patch\\n*** Update File: src/a.ts\\n@@\\n-old\\n+new'
        )

        argument_name, streamed_input = self.brain._extract_partial_streamable_tool_input(
            raw_output,
            "apply_patch",
        )

        self.assertEqual(argument_name, "patch")
        self.assertIn("*** Update File: src/a.ts", streamed_input or "")

    def test_completion_to_decision_uses_native_tool_calls(self) -> None:
        decision = self.brain._completion_to_decision(
            CompletionResponse(
                reasoning_text="Need to inspect the file first.",
                tool_calls=[
                    CompletionToolCall(
                        id="call_1",
                        name="read_file",
                        arguments='{"filename":"README.md"}',
                    )
                ]
            )
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.thought, "Need to inspect the file first.")
        self.assertEqual(
            decision.normalized_tool_calls(),
            [{"tool_name": "read_file", "tool_arguments": {"filename": "README.md"}}],
        )


class _NativeClient:
    def chat_completion_messages(self, messages, tools=None, tool_choice=None):  # noqa: ANN001
        return CompletionResponse(
            tool_calls=[
                CompletionToolCall(
                    id="call_1",
                    name="read_file",
                    arguments='{"filename":"README.md"}',
                )
            ]
        )


class _LegacyFallbackClient:
    def chat_completion_messages(self, messages, tools=None, tool_choice=None):  # noqa: ANN001
        raise UnsupportedToolCallingError("tools unsupported")

    def chat_messages(self, messages):  # noqa: ANN001
        return '{"action":"tool","tool_name":"read_file","tool_arguments":{"filename":"README.md"}}'


class _EmptyNativeThenLegacyClient:
    def chat_completion_messages(self, messages, tools=None, tool_choice=None):  # noqa: ANN001
        return CompletionResponse()

    def chat_messages(self, messages):  # noqa: ANN001
        return '{"action":"final","thought":"结束","final_answer":"fallback ok"}'


class _NativeStreamingClient:
    def chat_stream_completion_messages(self, messages, tools=None, on_text_delta=None, on_reasoning_delta=None, on_tool_call_delta=None):  # noqa: ANN001
        if on_reasoning_delta is not None:
            on_reasoning_delta("Need to inspect")
        if on_text_delta is not None:
            on_text_delta("first")
            on_text_delta(" second")
        if on_tool_call_delta is not None:
            from agent.llm_client import CompletionToolCallDelta

            on_tool_call_delta(
                CompletionToolCallDelta(
                    index=0,
                    id="call_1",
                    name="apply_patch",
                    arguments_delta='{"patch":"*** Begin Patch',
                    arguments='{"patch":"*** Begin Patch',
                )
            )
        return CompletionResponse(text="first second", reasoning_text="Need to inspect")


class DecideModeTests(unittest.TestCase):
    def test_decide_prefers_native_tool_calling(self) -> None:
        brain = OpenAICompatibleBrain(client=_NativeClient())

        decision = brain.decide(
            state=AgentState(task="task", current_input="readme"),
            tool_definitions={
                "read_file": {
                    "description": "读取文件",
                    "parameters_schema": {
                        "type": "object",
                        "properties": {"filename": {"type": "string"}},
                        "required": ["filename"],
                    },
                }
            },
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "read_file")

    def test_decide_falls_back_to_legacy_json_when_tools_unsupported(self) -> None:
        brain = OpenAICompatibleBrain(client=_LegacyFallbackClient())

        decision = brain.decide(
            state=AgentState(task="task", current_input="readme"),
            tool_definitions={"read_file": {"description": "读取文件", "parameters_schema": None}},
        )

        self.assertEqual(decision.action, "tool")
        self.assertEqual(decision.tool_name, "read_file")

    def test_decide_falls_back_to_legacy_json_when_native_response_is_empty(self) -> None:
        brain = OpenAICompatibleBrain(client=_EmptyNativeThenLegacyClient())

        decision = brain.decide(
            state=AgentState(task="task", current_input="hello"),
            tool_definitions={"read_file": {"description": "读取文件", "parameters_schema": None}},
        )

        self.assertEqual(decision.action, "final")
        self.assertEqual(decision.final_answer, "fallback ok")

    def test_native_streaming_callback_does_not_crash(self) -> None:
        brain = OpenAICompatibleBrain(client=_NativeStreamingClient())
        updates = []

        decision = brain.decide(
            state=AgentState(task="task", current_input="readme"),
            tool_definitions={"read_file": {"description": "读取文件", "parameters_schema": None}},
            on_stream=updates.append,
        )

        self.assertEqual(decision.action, "final")
        self.assertEqual(decision.final_answer, "first second")
        self.assertEqual(decision.thought, "Need to inspect")
        self.assertTrue(any(update.final_answer for update in updates))
        self.assertTrue(any(update.thought for update in updates))


if __name__ == "__main__":
    unittest.main()
