import unittest

from fastapi_app.ui_message_stream import UIMessageStreamAdapter


class UIMessageStreamAdapterTests(unittest.TestCase):
    def test_converts_text_stream_to_ui_message_parts(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = []
        parts.extend(adapter.convert({"type": "assistant_started", "payload": {"id": "m_1"}}))
        parts.extend(adapter.convert({"type": "assistant_delta", "payload": {"id": "m_1", "delta": "你好"}}))
        parts.extend(adapter.convert({"type": "assistant_done", "payload": {"id": "m_1"}}))

        self.assertEqual(parts[0], {"type": "start", "messageId": "m_1"})
        self.assertEqual(parts[1], {"type": "start-step"})
        self.assertEqual(parts[2]["type"], "text-start")
        self.assertEqual(parts[3]["type"], "text-delta")
        self.assertEqual(parts[3]["delta"], "你好")
        self.assertEqual(parts[4]["type"], "text-end")
        self.assertEqual(parts[-2], {"type": "finish-step"})
        self.assertEqual(parts[-1], {"type": "finish"})

    def test_converts_tool_call_and_result_parts(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = []
        parts.extend(adapter.convert({"type": "assistant_started", "payload": {"id": "m_1"}}))
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_call",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "read_file",
                        "arguments": {"filename": "README.md"},
                    },
                }
            )
        )
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_result",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "read_file",
                        "output": "content",
                        "success": True,
                    },
                }
            )
        )

        tool_input = next(part for part in parts if part["type"] == "tool-input-available")
        tool_output = next(part for part in parts if part["type"] == "tool-output-available")

        self.assertEqual(tool_input["toolCallId"], "call_1")
        self.assertEqual(tool_input["toolName"], "read_file")
        self.assertEqual(tool_input["input"], {"filename": "README.md"})
        self.assertEqual(tool_output["toolCallId"], "call_1")
        self.assertEqual(tool_output["output"], "content")

    def test_converts_realtime_tool_input_delta_before_available(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = []
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_input_started",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "write_file",
                    },
                }
            )
        )
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_input_delta",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "write_file",
                        "delta": "export function Chart() {\n",
                    },
                }
            )
        )
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_input_delta",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "write_file",
                        "delta": "  return null;\n}\n",
                    },
                }
            )
        )
        parts.extend(
            adapter.convert(
                {
                    "type": "tool_call",
                    "payload": {
                        "assistant_id": "m_1",
                        "id": "call_1",
                        "name": "write_file",
                        "arguments": {
                            "filename": "chart.tsx",
                            "content": "export function Chart() {\n  return null;\n}\n",
                        },
                    },
                }
            )
        )

        part_types = [part["type"] for part in parts]
        self.assertEqual(part_types.count("tool-input-start"), 1)
        self.assertEqual(part_types.count("tool-input-available"), 1)
        self.assertEqual(part_types.count("tool-input-delta"), 2)
        streamed = "".join(
            str(part["inputTextDelta"])
            for part in parts
            if part["type"] == "tool-input-delta"
        )
        self.assertEqual(streamed, "export function Chart() {\n  return null;\n}\n")

    def test_tool_call_does_not_replay_full_content_as_fake_deltas(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = adapter.convert(
            {
                "type": "tool_call",
                "payload": {
                    "assistant_id": "m_1",
                    "id": "call_1",
                    "name": "write_file",
                    "arguments": {
                        "filename": "chart.tsx",
                        "content": "export function Chart() {\n  return null;\n}\n",
                    },
                },
            }
        )

        part_types = [part["type"] for part in parts]
        self.assertIn("tool-input-available", part_types)
        self.assertNotIn("tool-input-delta", part_types)

    def test_forwards_custom_data_parts_from_tool_output(self) -> None:
        adapter = UIMessageStreamAdapter()

        parts = adapter.convert(
            {
                "type": "tool_result",
                "payload": {
                    "assistant_id": "m_1",
                    "id": "call_1",
                    "name": "chart",
                    "output": {
                        "type": "data-chart",
                        "data": {"title": "销售趋势", "points": [{"x": "Jan", "y": 12}]},
                    },
                    "success": True,
                },
            }
        )

        chart_part = next(part for part in parts if part["type"] == "data-chart")
        self.assertEqual(chart_part["data"]["title"], "销售趋势")


if __name__ == "__main__":
    unittest.main()
