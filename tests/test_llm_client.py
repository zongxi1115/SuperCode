import unittest
import ssl
import tempfile
from pathlib import Path

from agent.config import AgentLLMConfig
from agent.llm_client import CompletionResponse
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
                            "reasoning_content": "Need to read the file first.",
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
        self.assertEqual(response.reasoning_text, "Need to read the file first.")
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

    def test_extract_stream_reasoning_text_reads_reasoning_content(self) -> None:
        reasoning = self.client._extract_stream_reasoning_text(
            {
                "delta": {
                    "reasoning_content": "Need to inspect the file first.",
                }
            }
        )

        self.assertEqual(reasoning, "Need to inspect the file first.")

    def test_retries_empty_non_stream_completion(self) -> None:
        class RetryClient(OpenAICompatibleClient):
            def __init__(self, config):  # noqa: ANN001
                super().__init__(config)
                self.calls = 0

            def _sleep_before_retry(self, attempt: int) -> None:
                return None

            def _send_chat_request(self, messages, stream, tools=None, tool_choice=None):  # noqa: ANN001
                self.calls += 1
                if self.calls == 1:
                    return '{"choices":[{"message":{"content":""},"finish_reason":"stop"}]}'
                return '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        client = RetryClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
                max_retries=1,
            )
        )

        response = client.chat_completion_messages([{"role": "user", "content": "hi"}])

        self.assertEqual(response.text, "ok")
        self.assertEqual(client.calls, 2)

    def test_retries_stream_ssl_eof_before_any_delta(self) -> None:
        class RetryClient(OpenAICompatibleClient):
            def __init__(self, config):  # noqa: ANN001
                super().__init__(config)
                self.calls = 0

            def _sleep_before_retry(self, attempt: int) -> None:
                return None

            def _chat_stream_completion_messages_once(self, **kwargs):  # noqa: ANN003
                self.calls += 1
                if self.calls == 1:
                    raise ssl.SSLError("[SSL: UNEXPECTED_EOF_WHILE_READING]")
                on_text_delta = kwargs.get("on_text_delta")
                if on_text_delta is not None:
                    on_text_delta("ok")
                return CompletionResponse(text="ok")

        client = RetryClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
                max_retries=1,
            )
        )
        deltas: list[str] = []

        response = client.chat_stream_completion_messages(
            [{"role": "user", "content": "hi"}],
            on_text_delta=deltas.append,
        )

        self.assertEqual(response.text, "ok")
        self.assertEqual(deltas, ["ok"])
        self.assertEqual(client.calls, 2)


class ConfigParsingTests(unittest.TestCase):
    def test_include_thoughts_in_context_defaults_to_false(self) -> None:
        env_path = Path(tempfile.mkdtemp(prefix="supercode-config-")) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=key",
                    "SC_AGENT_BASE_URL=https://example.com/v1",
                    "SC_AGENT_MODEL=demo-model",
                ]
            ),
            encoding="utf-8",
        )

        config = AgentLLMConfig.from_env(env_path)

        self.assertFalse(config.include_thoughts_in_context)

    def test_include_thoughts_in_context_can_be_enabled(self) -> None:
        env_path = Path(tempfile.mkdtemp(prefix="supercode-config-")) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=key",
                    "SC_AGENT_BASE_URL=https://example.com/v1",
                    "SC_AGENT_MODEL=demo-model",
                    "SC_AGENT_INCLUDE_THOUGHTS_IN_CONTEXT=true",
                ]
            ),
            encoding="utf-8",
        )

        config = AgentLLMConfig.from_env(env_path)

        self.assertTrue(config.include_thoughts_in_context)


if __name__ == "__main__":
    unittest.main()
