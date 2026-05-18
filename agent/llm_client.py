from __future__ import annotations

import json
import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from http.client import RemoteDisconnected
from typing import Any
from collections.abc import Callable
from urllib import error, request

from .config import AgentLLMConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CompletionToolCall:
    id: str
    name: str
    arguments: str


@dataclass(slots=True)
class CompletionToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""
    arguments: str = ""


@dataclass(slots=True)
class CompletionResponse:
    text: str = ""
    reasoning_text: str = ""
    tool_calls: list[CompletionToolCall] = field(default_factory=list)
    finish_reason: str | None = None


class UnsupportedToolCallingError(RuntimeError):
    """模型服务不支持 tools / tool_choice 参数。"""


class OpenAICompatibleClient:
    """一个极简的 OpenAI 兼容接口客户端。"""

    def __init__(self, config: AgentLLMConfig) -> None:
        self.config = config

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """向模型发送一轮对话并返回文本内容。"""

        return self.chat_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def chat_messages(self, messages: list[dict[str, str]]) -> str:
        """向模型发送一轮消息数组并返回文本内容。"""

        response = self.chat_completion_messages(messages)
        if not response.text:
            raise RuntimeError("模型接口没有返回可用文本内容。")
        return response.text

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """以 OpenAI 兼容 SSE 方式流式获取文本。"""

        return self.chat_stream_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            on_delta=on_delta,
        )

    def chat_stream_messages(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """以 OpenAI 兼容 SSE 方式流式获取文本，支持直接传 messages 数组。"""

        response = self.chat_stream_completion_messages(
            messages,
            on_text_delta=on_delta,
        )
        if not response.text:
            raise RuntimeError("模型流式接口没有返回可用文本内容。")
        return response.text

    def chat_completion_messages(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> CompletionResponse:
        """发送非流式 chat/completions，并解析文本或 tool_calls。"""

        attempts = self._max_attempts()
        for attempt in range(attempts):
            try:
                response_body = self._send_chat_request(
                    messages=messages,
                    stream=False,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                data = json.loads(response_body)
                self._log_usage(data.get("usage"))
                completion = self._extract_chat_completion_response(data)
                if self._completion_has_content(completion) or attempt == attempts - 1:
                    return completion
                self._sleep_before_retry(attempt)
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if tools and self._should_fallback_to_non_tool_calling(exc.code, error_body):
                    raise UnsupportedToolCallingError(error_body) from exc
                if self._should_retry_http(exc.code) and attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
            except self._transient_error_types() as exc:
                if attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口连接失败: {self._format_connection_error(exc)}") from exc

        raise RuntimeError("模型接口没有返回可用文本内容。")

    def chat_stream_completion_messages(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
        """以 SSE 方式流式获取文本和 tool_calls。"""

        attempts = self._max_attempts()
        emitted_any_delta = False

        def handle_text_delta(delta: str) -> None:
            nonlocal emitted_any_delta
            if delta:
                emitted_any_delta = True
            if on_text_delta is not None:
                on_text_delta(delta)

        def handle_tool_call_delta(delta: CompletionToolCallDelta) -> None:
            nonlocal emitted_any_delta
            if delta.name or delta.arguments_delta or delta.arguments:
                emitted_any_delta = True
            if on_tool_call_delta is not None:
                on_tool_call_delta(delta)

        for attempt in range(attempts):
            try:
                completion = self._chat_stream_completion_messages_once(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    on_text_delta=handle_text_delta,
                    on_reasoning_delta=on_reasoning_delta,
                    on_tool_call_delta=handle_tool_call_delta,
                )
                if self._completion_has_content(completion) or attempt == attempts - 1:
                    return completion
                self._sleep_before_retry(attempt)
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if tools and self._should_fallback_to_non_tool_calling(exc.code, error_body):
                    raise UnsupportedToolCallingError(error_body) from exc
                if self._should_fallback_to_non_stream(exc.code, error_body):
                    return self.chat_completion_messages(
                        messages,
                        tools=tools,
                        tool_choice=tool_choice,
                    )
                if not emitted_any_delta and self._should_retry_http(exc.code) and attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
            except self._transient_error_types() as exc:
                if not emitted_any_delta and attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口连接失败: {self._format_connection_error(exc)}") from exc

        raise RuntimeError("模型流式接口没有返回可用文本内容。")

    def _chat_stream_completion_messages_once(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
        """执行一次 SSE 请求；重试策略由调用方控制。"""

        api_url = f"{self.config.base_url}/chat/completions"
        http_request = self._build_request(
            messages=messages,
            stream=True,
            api_url=api_url,
            tools=tools,
            tool_choice=tool_choice,
        )
        with request.urlopen(http_request, timeout=self.config.timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" not in content_type.lower():
                response_body = response.read().decode("utf-8")
                data = json.loads(response_body)
                self._log_usage(data.get("usage"))
                completion = self._extract_chat_completion_response(data)
                if completion.reasoning_text and on_reasoning_delta is not None:
                    on_reasoning_delta(completion.reasoning_text)
                if completion.text and on_text_delta is not None:
                    on_text_delta(completion.text)
                for index, tool_call in enumerate(completion.tool_calls):
                    if on_tool_call_delta is not None:
                        on_tool_call_delta(
                            CompletionToolCallDelta(
                                index=index,
                                id=tool_call.id,
                                name=tool_call.name,
                                arguments_delta=tool_call.arguments,
                                arguments=tool_call.arguments,
                            )
                        )
                return completion

            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            last_usage: object | None = None
            finish_reason: str | None = None
            tool_call_buffers: dict[int, dict[str, Any]] = {}

            for event_text in self._iter_sse_events(response):
                if event_text == "[DONE]":
                    break

                payload = json.loads(event_text)
                usage = payload.get("usage")
                if usage is not None:
                    last_usage = usage

                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue

                first_choice = choices[0]
                if not isinstance(first_choice, dict):
                    continue

                raw_finish_reason = first_choice.get("finish_reason")
                if isinstance(raw_finish_reason, str) and raw_finish_reason:
                    finish_reason = raw_finish_reason

                delta_text = self._extract_stream_text(payload)
                if delta_text:
                    text_parts.append(delta_text)
                    if on_text_delta is not None:
                        on_text_delta(delta_text)

                reasoning_delta = self._extract_stream_reasoning_text(first_choice)
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
                    if on_reasoning_delta is not None:
                        on_reasoning_delta(reasoning_delta)

                for tool_delta in self._extract_stream_tool_call_deltas(first_choice, tool_call_buffers):
                    if on_tool_call_delta is not None:
                        on_tool_call_delta(tool_delta)

            self._log_usage(last_usage)
            return CompletionResponse(
                text="".join(text_parts).strip(),
                reasoning_text="".join(reasoning_parts).strip(),
                tool_calls=self._finalize_stream_tool_calls(tool_call_buffers),
                finish_reason=finish_reason,
            )

    def _build_request(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        api_url: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> request.Request:
        payload: dict[str, object] = {
            "model": self.config.model,
            "temperature": 0.2,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if stream and self._is_deepseek_request():
            payload["stream_options"] = {"include_usage": True}
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "curl/8.4.0",
        }
        return request.Request(api_url, data=body, headers=headers, method="POST")

    def _send_chat_request(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> str:
        api_url = f"{self.config.base_url}/chat/completions"
        http_request = self._build_request(
            messages=messages,
            stream=stream,
            api_url=api_url,
            tools=tools,
            tool_choice=tool_choice,
        )
        with request.urlopen(http_request, timeout=self.config.timeout) as response:
            return response.read().decode("utf-8")

    def _extract_chat_completion_response(self, data: dict[str, object]) -> CompletionResponse:
        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("模型接口返回中没有 `choices` 字段内容。")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("模型接口返回的 `choices[0]` 不是对象。")

        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            message = {}

        text = self._flatten_content(message.get("content")).strip()
        if not text:
            text = self._flatten_content(first_choice.get("text")).strip()
        reasoning_text = self._flatten_reasoning_content(message.get("reasoning_content")).strip()

        tool_calls = self._extract_message_tool_calls(message)
        finish_reason = first_choice.get("finish_reason")
        normalized_finish_reason = finish_reason if isinstance(finish_reason, str) else None

        return CompletionResponse(
            text=text,
            reasoning_text=reasoning_text,
            tool_calls=tool_calls,
            finish_reason=normalized_finish_reason,
        )

    def _extract_message_tool_calls(self, message: dict[str, object]) -> list[CompletionToolCall]:
        raw_tool_calls = message.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            return []

        tool_calls: list[CompletionToolCall] = []
        for index, item in enumerate(raw_tool_calls):
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name", "")).strip()
            arguments = function.get("arguments", "")
            if not name:
                continue
            tool_calls.append(
                CompletionToolCall(
                    id=str(item.get("id") or f"tool-call-{index}"),
                    name=name,
                    arguments=arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
                )
            )
        return tool_calls

    def _extract_stream_tool_call_deltas(
        self,
        first_choice: dict[str, object],
        tool_call_buffers: dict[int, dict[str, Any]],
    ) -> list[CompletionToolCallDelta]:
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return []

        raw_tool_calls = delta.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            return []

        deltas: list[CompletionToolCallDelta] = []
        for position, item in enumerate(raw_tool_calls):
            if not isinstance(item, dict):
                continue
            raw_index = item.get("index", position)
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                index = position

            buffer = tool_call_buffers.setdefault(
                index,
                {
                    "id": None,
                    "name": None,
                    "arguments_parts": [],
                },
            )

            item_id = item.get("id")
            if isinstance(item_id, str) and item_id:
                buffer["id"] = item_id

            function = item.get("function")
            arguments_delta = ""
            if isinstance(function, dict):
                function_name = function.get("name")
                if isinstance(function_name, str) and function_name:
                    buffer["name"] = function_name
                raw_arguments_delta = function.get("arguments")
                if isinstance(raw_arguments_delta, str) and raw_arguments_delta:
                    arguments_delta = raw_arguments_delta
                    buffer["arguments_parts"].append(raw_arguments_delta)

            deltas.append(
                CompletionToolCallDelta(
                    index=index,
                    id=buffer["id"],
                    name=buffer["name"],
                    arguments_delta=arguments_delta,
                    arguments="".join(buffer["arguments_parts"]),
                )
            )

        return deltas

    def _finalize_stream_tool_calls(
        self,
        tool_call_buffers: dict[int, dict[str, Any]],
    ) -> list[CompletionToolCall]:
        tool_calls: list[CompletionToolCall] = []
        for index in sorted(tool_call_buffers):
            buffer = tool_call_buffers[index]
            name = str(buffer.get("name") or "").strip()
            if not name:
                continue
            tool_calls.append(
                CompletionToolCall(
                    id=str(buffer.get("id") or f"tool-call-{index}"),
                    name=name,
                    arguments="".join(buffer.get("arguments_parts", [])),
                )
            )
        return tool_calls

    def _log_usage(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        hit_tokens = usage.get("prompt_cache_hit_tokens")
        miss_tokens = usage.get("prompt_cache_miss_tokens")
        if not any(value is not None for value in (prompt_tokens, completion_tokens, hit_tokens, miss_tokens)):
            return

        extra_parts: list[str] = []
        if isinstance(prompt_tokens, int):
            extra_parts.append(f"prompt_tokens={prompt_tokens}")
        if isinstance(completion_tokens, int):
            extra_parts.append(f"completion_tokens={completion_tokens}")
        if isinstance(hit_tokens, int):
            extra_parts.append(f"cache_hit={hit_tokens}")
        if isinstance(miss_tokens, int):
            extra_parts.append(f"cache_miss={miss_tokens}")
        if isinstance(hit_tokens, int) and isinstance(miss_tokens, int) and (hit_tokens + miss_tokens) > 0:
            hit_rate = hit_tokens / (hit_tokens + miss_tokens)
            extra_parts.append(f"cache_hit_rate={hit_rate:.1%}")

        logger.info("LLM usage: %s", ", ".join(extra_parts))

    def _is_deepseek_request(self) -> bool:
        model_lower = self.config.model.lower()
        base_url_lower = self.config.base_url.lower()
        return "deepseek" in model_lower or "deepseek" in base_url_lower

    def _iter_sse_events(self, response: object):
        current_lines: list[str] = []

        for raw_line in response:  # type: ignore[assignment]
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if current_lines:
                    data_text = "\n".join(
                        line_part.removeprefix("data:").lstrip()
                        for line_part in current_lines
                        if line_part.startswith("data:")
                    )
                    if data_text:
                        yield data_text
                    current_lines = []
                continue

            if line.startswith(":"):
                continue
            current_lines.append(line)

        if current_lines:
            data_text = "\n".join(
                line_part.removeprefix("data:").lstrip()
                for line_part in current_lines
                if line_part.startswith("data:")
            )
            if data_text:
                yield data_text

    def _extract_stream_text(self, payload: dict[str, object]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return ""

        delta = first_choice.get("delta")
        if isinstance(delta, dict):
            content = self._flatten_content(delta.get("content"))
            if content:
                return content

        message = first_choice.get("message")
        if isinstance(message, dict):
            content = self._flatten_content(message.get("content"))
            if content:
                return content

        return self._flatten_content(first_choice.get("text"))

    def _extract_stream_reasoning_text(self, first_choice: dict[str, object]) -> str:
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return ""
        return self._flatten_reasoning_content(delta.get("reasoning_content"))

    def _flatten_content(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""

        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
                continue

            nested_text = item.get("content")
            if isinstance(nested_text, str):
                parts.append(nested_text)
        return "".join(parts)

    def _flatten_reasoning_content(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""

        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)

    def _should_fallback_to_non_stream(self, status_code: int, error_body: str) -> bool:
        if status_code not in {400, 404, 405, 415, 422, 501}:
            return False

        normalized = error_body.lower()
        hints = [
            "stream",
            "sse",
            "event-stream",
            "not support",
            "unsupported",
            "invalid parameter",
        ]
        return any(hint in normalized for hint in hints)

    def _max_attempts(self) -> int:
        return max(1, int(getattr(self.config, "max_retries", 2)) + 1)

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(min(2.0, 0.25 * (2 ** attempt)))

    def _completion_has_content(self, completion: CompletionResponse) -> bool:
        return bool(completion.text.strip() or completion.tool_calls)

    def _should_retry_http(self, status_code: int) -> bool:
        return status_code in {408, 409, 425, 429, 500, 502, 503, 504}

    def _transient_error_types(self) -> tuple[type[BaseException], ...]:
        return (
            error.URLError,
            TimeoutError,
            socket.timeout,
            ssl.SSLError,
            RemoteDisconnected,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
        )

    def _format_connection_error(self, exc: BaseException) -> object:
        if isinstance(exc, error.URLError):
            return exc.reason
        return exc

    def _should_fallback_to_non_tool_calling(self, status_code: int, error_body: str) -> bool:
        if status_code not in {400, 404, 405, 415, 422, 501}:
            return False

        normalized = error_body.lower()
        hints = [
            "\"tools\"",
            "tools",
            "tool_choice",
            "function call",
            "function_call",
            "tool calls",
            "does not support tool",
            "unsupported tool",
            "invalid parameter",
        ]
        return any(hint in normalized for hint in hints)
