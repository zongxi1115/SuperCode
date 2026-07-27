import unittest

from agent.llm_client import CompletionResponse, CompletionToolCall, UnsupportedToolCallingError
from agent.openai_model import OpenAICompatibleModel
from agent.schema import AgentState
from zonix.models.base import ModelRequest


class ParseJsonOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = OpenAICompatibleModel(client=object())

    def test_parse_single_json_object(self) -> None:
        payload = self.model._parse_json_output(
            '{"action":"final","thought":"done","final_answer":"ok"}'
        )

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_parse_first_json_object_from_mixed_output(self) -> None:
        raw_output = """{"action":"tool","thought":"先写文件","tool_name":"write_file","tool_arguments":{"filename":"sudoku.py","content":"print(1)"}}\n</think>\n\n{"action":"final","thought":"结束","final_answer":"done"}"""

        payload = self.model._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "tool")
        self.assertEqual(payload["tool_name"], "write_file")

    def test_parse_skips_non_step_dicts(self) -> None:
        raw_output = """分析过程里先出现了一个普通对象 {"filename":"demo.py","content":"print(1)"}，真正的决策在后面 {"action":"final","thought":"结束","final_answer":"ok"}"""

        payload = self.model._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "final")
        self.assertEqual(payload["final_answer"], "ok")

    def test_to_step_can_infer_tool_action(self) -> None:
        step = self.model._to_step(
            {
                "thought": "直接调用工具",
                "tool_name": "read_file",
                "tool_arguments": {"filename": "README.md"},
            }
        )

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.tool_name, "read_file")

    def test_to_step_can_infer_final_action(self) -> None:
        step = self.model._to_step(
            {
                "thought": "直接结束",
                "final_answer": "done",
            }
        )

        self.assertEqual(step.action, "final")
        self.assertEqual(step.final_answer, "done")

    def test_to_step_accepts_tool_and_args_aliases(self) -> None:
        step = self.model._to_step(
            {
                "tool": "read_file",
                "args": {"filename": "README.md"},
            }
        )

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.tool_name, "read_file")
        self.assertEqual(step.tool_arguments, {"filename": "README.md"})

    def test_extracts_partial_write_file_content_for_realtime_tool_input(self) -> None:
        raw_output = (
            '{"action":"tool","tool_name":"write_file",'
            '"tool_arguments":{"filename":"demo.ts","content":"export const a = 1'
        )

        argument_name, streamed_input = self.model._extract_partial_streamable_tool_input(
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
        argument_name, streamed_input = self.model._extract_partial_streamable_tool_input(
            old_only,
            "replace_file",
        )

        self.assertIsNone(argument_name)
        self.assertIsNone(streamed_input)

        with_new_content = (
            old_only
            + '","new_content":"after'
        )
        argument_name, streamed_input = self.model._extract_partial_streamable_tool_input(
            with_new_content,
            "replace_file",
        )

        self.assertEqual(argument_name, "new_content")
        self.assertEqual(streamed_input, "after")

    def test_extracts_partial_apply_patch_content_for_realtime_tool_input(self) -> None:
        raw_output = (
            '{"action":"tool","tool_name":"apply_patch",'
            '"tool_arguments":{"filename":"src/a.ts","start_line":1,"end_line":1,"new_content":"const after = 1;'
        )

        argument_name, streamed_input = self.model._extract_partial_streamable_tool_input(
            raw_output,
            "apply_patch",
        )

        self.assertEqual(argument_name, "new_content")
        self.assertEqual(streamed_input, "const after = 1;")

    def test_extracts_partial_save_plan_arguments_for_realtime_tool_input(self) -> None:
        raw_output = (
            '{"title":"在线 OJ 系统第一期实施计划",'
            '"summary":"基于 FastAPI + React + go-judge 构建在线判题系统第一期",'
            '"overview":"本计划将搭建一个完整的在线 OJ 系统",'
            '"key_steps":["用户系统","题目管理"],'
            '"markdown":"# 在线 OJ'
        )

        argument_name, streamed_input = self.model._extract_partial_streamable_tool_input(
            raw_output,
            "save_plan",
        )

        self.assertEqual(argument_name, "arguments")
        self.assertIn('"title":"在线 OJ 系统第一期实施计划"', streamed_input or "")
        self.assertIn('"markdown":"# 在线 OJ', streamed_input or "")

    def test_parse_tool_arguments_text_recovers_invalid_save_plan_json(self) -> None:
        parsed = self.model._parse_tool_arguments_text(
            (
                '{"title":"SuperDocs AI Coding Agent —— 从零搭建计划",'
                '"summary":"基于 Python + Anthropic Claude API",'
                '"overview":"本计划目标是开发一个 CLI 命令行 AI Coding Agent",'
                '"key_steps":["搭 CLI","接 Claude API"],'
                '"markdown":"# SuperDocs'
            ),
            "save_plan",
        )

        self.assertEqual(parsed["title"], "SuperDocs AI Coding Agent —— 从零搭建计划")
        self.assertEqual(parsed["summary"], "基于 Python + Anthropic Claude API")
        self.assertEqual(parsed["key_steps"], ["搭 CLI", "接 Claude API"])

    def test_parse_tool_arguments_text_recovers_write_file_html_content(self) -> None:
        arguments = (
            '{"filename":"index.html","content":"<!doctype html>\n'
            '<div class="hero" data-json=\'{"msg":"hi"}\'>\n'
            '  <script>\n'
            '    const raw = "\\\\n";\n'
            '  </script>\n'
            '</div>"}'
        )
        expected = "\n".join(
            [
                "<!doctype html>",
                '<div class="hero" data-json=\'{"msg":"hi"}\'>',
                "  <script>",
                '    const raw = "\\n";',
                "  </script>",
                "</div>",
            ]
        )

        parsed = self.model._parse_tool_arguments_text(arguments, "write_file")

        self.assertEqual(parsed["filename"], "index.html")
        self.assertEqual(parsed["content"], expected)

    def test_parse_json_output_recovers_nested_write_file_arguments(self) -> None:
        raw_output = (
            '{"action":"tool","thought":"写入首页","tool_name":"write_file","tool_arguments":'
            '{"filename":"index.html","content":"<!doctype html>\n'
            '<div class="hero">\n'
            '  <script>\n'
            '    const raw = "\\\\n";\n'
            "  </script>\n"
            '</div>"}}'
        )
        expected = "\n".join(
            [
                "<!doctype html>",
                '<div class="hero">',
                "  <script>",
                '    const raw = "\\n";',
                "  </script>",
                "</div>",
            ]
        )

        payload = self.model._parse_json_output(raw_output)

        self.assertEqual(payload["action"], "tool")
        self.assertEqual(payload["tool_name"], "write_file")
        self.assertEqual(payload["tool_arguments"]["filename"], "index.html")
        self.assertEqual(payload["tool_arguments"]["content"], expected)

    def test_parse_tool_arguments_text_decodes_escaped_newlines_in_tsx_content(self) -> None:
        arguments = '''{"filename":"AdminPage.tsx","content":"import { useState, useEffect } from 'react'\\nimport './AdminPage.css'\\n\\nfunction AdminPage() {\\n  return (\\n    <div className=\\"admin-page\\" data-label="管理页面">\\n      <input placeholder="标题" />\\n    </div>\\n  )\\n}"}'''

        parsed = self.model._parse_tool_arguments_text(arguments, "write_file")

        self.assertEqual(parsed["filename"], "AdminPage.tsx")
        self.assertEqual(
            parsed["content"],
            """import { useState, useEffect } from 'react'
import './AdminPage.css'

function AdminPage() {
  return (
    <div className=\"admin-page\" data-label=\"管理页面\">
      <input placeholder=\"标题\" />
    </div>
  )
}""",
        )

    def test_completion_to_step_uses_native_tool_calls(self) -> None:
        step = self.model._completion_to_step(
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

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.thought, "Need to inspect the file first.")
        self.assertEqual(
            step.normalized_tool_calls(),
            [
                {
                    "tool_call_id": "call_1",
                    "tool_name": "read_file",
                    "tool_arguments": {"filename": "README.md"},
                }
            ],
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


class _NativeStreamingToolClient:
    def chat_stream_completion_messages(self, messages, tools=None, on_text_delta=None, on_reasoning_delta=None, on_tool_call_delta=None):  # noqa: ANN001
        if on_reasoning_delta is not None:
            on_reasoning_delta("Need to inspect")
        if on_text_delta is not None:
            on_text_delta("<template>")
            on_text_delta("\n<div>partial</div>")
        if on_tool_call_delta is not None:
            from agent.llm_client import CompletionToolCallDelta

            on_tool_call_delta(
                CompletionToolCallDelta(
                    index=0,
                    id="call_1",
                    name="apply_patch",
                    arguments_delta='{"filename":"App.vue","start_line":1,"end_line":1,"new_content":"<template>',
                    arguments='{"filename":"App.vue","start_line":1,"end_line":1,"new_content":"<template>',
                )
            )
        return CompletionResponse(
            reasoning_text="Need to inspect",
            tool_calls=[
                CompletionToolCall(
                    id="call_1",
                    name="apply_patch",
                    arguments='{"filename":"App.vue","start_line":1,"end_line":1,"new_content":"<template>"}',
                )
            ],
        )


class NextStepModeTests(unittest.TestCase):
    def test_next_step_prefers_native_tool_calling(self) -> None:
        model = OpenAICompatibleModel(client=_NativeClient())
        state = AgentState(task="task", current_input="readme")

        step = model._next_provider_step(
            request=ModelRequest(messages=[], task=state.current_input),
            state=state,
            tool_definitions={
                "read_file": {
                    "description": "读取文件",
                    "input_schema": {
                        "type": "object",
                        "properties": {"filename": {"type": "string"}},
                        "required": ["filename"],
                    },
                }
            },
        )

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.tool_name, "read_file")

    def test_next_step_falls_back_to_legacy_json_when_tools_unsupported(self) -> None:
        model = OpenAICompatibleModel(client=_LegacyFallbackClient())
        state = AgentState(task="task", current_input="readme")

        step = model._next_provider_step(
            request=ModelRequest(messages=[], task=state.current_input),
            state=state,
            tool_definitions={"read_file": {"description": "读取文件", "input_schema": None}},
        )

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.tool_name, "read_file")

    def test_next_step_falls_back_to_legacy_json_when_native_response_is_empty(self) -> None:
        model = OpenAICompatibleModel(client=_EmptyNativeThenLegacyClient())
        state = AgentState(task="task", current_input="hello")

        step = model._next_provider_step(
            request=ModelRequest(messages=[], task=state.current_input),
            state=state,
            tool_definitions={"read_file": {"description": "读取文件", "input_schema": None}},
        )

        self.assertEqual(step.action, "final")
        self.assertEqual(step.final_answer, "fallback ok")

    def test_native_streaming_callback_does_not_crash(self) -> None:
        model = OpenAICompatibleModel(client=_NativeStreamingClient())
        updates = []
        state = AgentState(task="task", current_input="readme")

        step = model._next_provider_step(
            request=ModelRequest(messages=[], task=state.current_input),
            state=state,
            tool_definitions={"read_file": {"description": "读取文件", "input_schema": None}},
            on_stream=updates.append,
        )

        self.assertEqual(step.action, "final")
        self.assertEqual(step.final_answer, "first second")
        self.assertEqual(step.thought, "Need to inspect")
        self.assertTrue(any(update.final_answer for update in updates))
        self.assertTrue(any(update.thought for update in updates))

    def test_native_streaming_tool_calls_do_not_emit_final_text_updates(self) -> None:
        model = OpenAICompatibleModel(client=_NativeStreamingToolClient())
        updates = []
        state = AgentState(task="task", current_input="patch app")

        step = model._next_provider_step(
            request=ModelRequest(messages=[], task=state.current_input),
            state=state,
            tool_definitions={"apply_patch": {"description": "修改文件", "input_schema": None}},
            on_stream=updates.append,
        )

        self.assertEqual(step.action, "tool")
        self.assertEqual(step.tool_name, "apply_patch")
        self.assertFalse(any(update.final_answer for update in updates))
        self.assertTrue(any(update.streamed_tool_name == "apply_patch" for update in updates))


if __name__ == "__main__":
    unittest.main()
