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

    def test_extract_responses_response_reads_tool_calls(self) -> None:
        response = self.client._extract_responses_response(
            {
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "Need to read the file first."}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": '{"filename":"README.md"}',
                    }
                ]
            }
        )

        self.assertEqual(response.finish_reason, "completed")
        self.assertEqual(response.reasoning_text, "Need to read the file first.")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, '{"filename":"README.md"}')

    def test_extract_response_stream_tool_call_delta_accumulates_arguments(self) -> None:
        buffers: dict[int, dict[str, object]] = {}
        self.client._capture_response_output_item(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "apply_patch",
                },
            },
            buffers,
            {},
        )

        deltas_first = self.client._extract_response_stream_tool_call_delta(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": "fc_1",
                "delta": '{"patch":"*** Begin Patch',
            },
            buffers,
        )
        deltas_second = self.client._extract_response_stream_tool_call_delta(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": "fc_1",
                "delta": '\\n*** End Patch"}',
            },
            buffers,
        )

        self.assertEqual(deltas_first[0].name, "apply_patch")
        self.assertIn("*** Begin Patch", deltas_first[0].arguments)
        self.assertIn("*** End Patch", deltas_second[0].arguments)

    def test_flatten_response_reasoning_text_reads_reasoning_summary(self) -> None:
        reasoning = self.client._flatten_response_reasoning_text(
            [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "Need to inspect the file first."}],
                }
            ]
        )

        self.assertEqual(reasoning, "Need to inspect the file first.")

    def test_log_usage_normalizes_openai_compatible_fields(self) -> None:
        self.client._log_usage(
            {
                "prompt_tokens": 1234,
                "completion_tokens": 210,
                "total_tokens": 1444,
                "prompt_tokens_details": {"cached_tokens": 320},
                "completion_tokens_details": {"reasoning_tokens": 64},
            }
        )

        self.assertEqual(
            self.client.last_usage,
            {
                "inputTokens": 1234,
                "outputTokens": 210,
                "reasoningTokens": 64,
                "cachedInputTokens": 320,
                "totalTokens": 1444,
            },
        )

    def test_build_chat_request_includes_reasoning_effort_when_configured(self) -> None:
        client = OpenAICompatibleClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
                reasoning_effort="high",
            )
        )

        request = client._build_request(
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
            api_url="https://example.com/v1/chat/completions",
        )

        payload = request.data.decode("utf-8")
        self.assertIn('"reasoning_effort": "high"', payload)
        self.assertNotIn('"reasoning": {"effort": "high"}', payload)

    def test_build_responses_request_includes_reasoning_effort_when_configured(self) -> None:
        client = OpenAICompatibleClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
                api_mode="responses",
                reasoning_effort="high",
            )
        )

        request = client._build_request(
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
            api_url="https://example.com/v1/responses",
        )

        payload = request.data.decode("utf-8")
        self.assertIn('"reasoning": {"effort": "high"}', payload)

    def test_retries_empty_non_stream_completion(self) -> None:
        class RetryClient(OpenAICompatibleClient):
            def __init__(self, config):  # noqa: ANN001
                super().__init__(config)
                self.calls = 0

            def _sleep_before_retry(self, attempt: int) -> None:
                return None

            def _send_responses_request(self, messages, stream, tools=None, tool_choice=None):  # noqa: ANN001
                self.calls += 1
                if self.calls == 1:
                    return '{"status":"completed","output":[]}'
                return '{"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok"}]}]}'

        client = RetryClient(
            AgentLLMConfig(
                api_key="key",
                base_url="https://example.com/v1",
                model="demo-model",
                api_mode="responses",
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

    def test_reasoning_effort_can_be_loaded_from_env(self) -> None:
        env_path = Path(tempfile.mkdtemp(prefix="supercode-config-")) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=key",
                    "SC_AGENT_BASE_URL=https://example.com/v1",
                    "SC_AGENT_MODEL=demo-model",
                    "SC_AGENT_REASONING_EFFORT=high",
                ]
            ),
            encoding="utf-8",
        )

        config = AgentLLMConfig.from_env(env_path)

        self.assertEqual(config.reasoning_effort, "high")

    def test_api_mode_defaults_to_chat_completions(self) -> None:
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

        self.assertEqual(config.api_mode, "chat_completions")

    def test_api_mode_can_be_loaded_from_env(self) -> None:
        env_path = Path(tempfile.mkdtemp(prefix="supercode-config-")) / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "SC_AGENT_API_KEY=key",
                    "SC_AGENT_BASE_URL=https://example.com/v1",
                    "SC_AGENT_MODEL=demo-model",
                    "SC_AGENT_API_MODE=responses",
                ]
            ),
            encoding="utf-8",
        )

        config = AgentLLMConfig.from_env(env_path)

        self.assertEqual(config.api_mode, "responses")


if __name__ == "__main__":
    unittest.main()
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
                            ],
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
