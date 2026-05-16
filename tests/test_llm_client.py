import unittest

from agent.config import AgentLLMConfig
from agent.llm_client import OpenAICompatibleClient


class ClientParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = OpenAICompatibleClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
            )
        )

    def test_extract_chat_completion_response_reads_tool_calls(self) -> None:
        response = self.client._extract_chat_completion_response(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"filename":"README.md"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )

        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, '{"filename":"README.md"}')

    def test_extract_stream_tool_call_deltas_accumulates_arguments(self) -> None:
        buffers: dict[int, dict[str, object]] = {}

        deltas_first = self.client._extract_stream_tool_call_deltas(
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "apply_patch",
                                "arguments": '{"patch":"*** Begin Patch',
                            },
                        }
                    ]
                }
            },
            buffers,
        )
        deltas_second = self.client._extract_stream_tool_call_deltas(
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {
                                "arguments": '\\n*** End Patch"}',
                            },
                        }
                    ]
                }
            },
            buffers,
        )

        self.assertEqual(deltas_first[0].name, "apply_patch")
        self.assertIn("*** Begin Patch", deltas_first[0].arguments)
        self.assertIn("*** End Patch", deltas_second[0].arguments)


if __name__ == "__main__":
    unittest.main()
