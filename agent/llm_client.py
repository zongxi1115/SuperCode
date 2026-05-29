from __future__ import annotations

import json
import logging
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.client import RemoteDisconnected
from typing import Any
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
    response_items: list[dict[str, object]] = field(default_factory=list)


class UnsupportedToolCallingError(RuntimeError):
    """模型服务不支持 tools / tool_choice 参数。"""


def _format_retry_delay(seconds: float) -> str:
    if seconds.is_integer():
        return f"{int(seconds)} 秒"
    return f"{seconds:.1f} 秒"


class OpenAICompatibleClient:
    """支持 chat/completions 与 responses 两种接口模式的极简客户端。"""

    def __init__(self, config: AgentLLMConfig) -> None:
        self.config = config
        self.last_usage: dict[str, int] | None = None

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        return self.chat_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def chat_messages(self, messages: list[dict[str, object]]) -> str:
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
        return self.chat_stream_messages(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            on_delta=on_delta,
        )

    def chat_stream_messages(
        self,
        messages: list[dict[str, object]],
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        response = self.chat_stream_completion_messages(
            messages,
            on_text_delta=on_delta,
        )
        if not response.text:
            raise RuntimeError("模型流式接口没有返回可用文本内容。")
        return response.text

    def chat_completion_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> CompletionResponse:
        if self._uses_responses_api():
            return self._responses_chat_completion_messages(
                messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        return self._chat_completions_messages(
            messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    def chat_stream_completion_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
        if self._uses_responses_api():
            return self._responses_chat_stream_completion_messages(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                on_text_delta=on_text_delta,
                on_reasoning_delta=on_reasoning_delta,
                on_tool_call_delta=on_tool_call_delta,
            )
        return self._chat_completions_stream_completion_messages(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            on_text_delta=on_text_delta,
            on_reasoning_delta=on_reasoning_delta,
            on_tool_call_delta=on_tool_call_delta,
        )

    def _chat_completions_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> CompletionResponse:
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

    def _chat_completions_stream_completion_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
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
                self._emit_retry_notice(
                    on_reasoning_delta,
                    attempt=attempt,
                    attempts=attempts,
                    error_message="模型流式接口没有返回可用内容。",
                )
                self._sleep_before_retry(attempt)
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if tools and self._should_fallback_to_non_tool_calling(exc.code, error_body):
                    raise UnsupportedToolCallingError(error_body) from exc
                if self._should_fallback_to_non_stream(exc.code, error_body):
                    return self._chat_completions_messages(
                        messages,
                        tools=tools,
                        tool_choice=tool_choice,
                    )
                if not emitted_any_delta and self._should_retry_http(exc.code) and attempt < attempts - 1:
                    self._emit_retry_notice(
                        on_reasoning_delta,
                        attempt=attempt,
                        attempts=attempts,
                        error_message=f"HTTP {exc.code} - {error_body}",
                    )
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
            except self._transient_error_types() as exc:
                if not emitted_any_delta and attempt < attempts - 1:
                    self._emit_retry_notice(
                        on_reasoning_delta,
                        attempt=attempt,
                        attempts=attempts,
                        error_message=self._format_connection_error(exc),
                    )
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口连接失败: {self._format_connection_error(exc)}") from exc
        raise RuntimeError("模型流式接口没有返回可用文本内容。")

    def _chat_stream_completion_messages_once(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
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

    def _responses_chat_completion_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> CompletionResponse:
        attempts = self._max_attempts()
        for attempt in range(attempts):
            try:
                response_body = self._send_responses_request(
                    messages=messages,
                    stream=False,
                    tools=tools,
                    tool_choice=tool_choice,
                )
                data = json.loads(response_body)
                self._log_usage(data.get("usage"))
                completion = self._extract_responses_response(data)
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

    def _responses_chat_stream_completion_messages(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
        attempts = self._max_attempts()
        emitted_any_delta = False

        def handle_text_delta(delta: str) -> None:
            nonlocal emitted_any_delta
            if delta:
                emitted_any_delta = True
            if on_text_delta is not None:
                on_text_delta(delta)

        def handle_reasoning_delta(delta: str) -> None:
            nonlocal emitted_any_delta
            if delta:
                emitted_any_delta = True
            if on_reasoning_delta is not None:
                on_reasoning_delta(delta)

        def handle_tool_call_delta(delta: CompletionToolCallDelta) -> None:
            nonlocal emitted_any_delta
            if delta.name or delta.arguments_delta or delta.arguments:
                emitted_any_delta = True
            if on_tool_call_delta is not None:
                on_tool_call_delta(delta)

        for attempt in range(attempts):
            try:
                completion = self._responses_stream_completion_messages_once(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    on_text_delta=handle_text_delta,
                    on_reasoning_delta=handle_reasoning_delta,
                    on_tool_call_delta=handle_tool_call_delta,
                )
                if self._completion_has_content(completion) or attempt == attempts - 1:
                    return completion
                self._emit_retry_notice(
                    on_reasoning_delta,
                    attempt=attempt,
                    attempts=attempts,
                    error_message="模型流式接口没有返回可用内容。",
                )
                self._sleep_before_retry(attempt)
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                if tools and self._should_fallback_to_non_tool_calling(exc.code, error_body):
                    raise UnsupportedToolCallingError(error_body) from exc
                if not emitted_any_delta and self._should_retry_http(exc.code) and attempt < attempts - 1:
                    self._emit_retry_notice(
                        on_reasoning_delta,
                        attempt=attempt,
                        attempts=attempts,
                        error_message=f"HTTP {exc.code} - {error_body}",
                    )
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
            except self._transient_error_types() as exc:
                if not emitted_any_delta and attempt < attempts - 1:
                    self._emit_retry_notice(
                        on_reasoning_delta,
                        attempt=attempt,
                        attempts=attempts,
                        error_message=self._format_connection_error(exc),
                    )
                    self._sleep_before_retry(attempt)
                    continue
                raise RuntimeError(f"模型接口连接失败: {self._format_connection_error(exc)}") from exc
        raise RuntimeError("模型流式接口没有返回可用文本内容。")

    def _responses_stream_completion_messages_once(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning_delta: Callable[[str], None] | None = None,
        on_tool_call_delta: Callable[[CompletionToolCallDelta], None] | None = None,
    ) -> CompletionResponse:
        api_url = f"{self.config.base_url}/responses"
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
                completion = self._extract_responses_response(data)
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
            tool_call_buffers: dict[int, dict[str, Any]] = {}
            stream_output_items: dict[int, dict[str, Any]] = {}
            final_response: dict[str, object] | None = None

            for event_text in self._iter_sse_events(response):
                if event_text == "[DONE]":
                    break

                payload = json.loads(event_text)
                event_type = str(payload.get("type") or "").strip()
                if not event_type:
                    continue

                if event_type == "response.output_text.delta":
                    delta_text = self._coerce_string(payload.get("delta"))
                    if delta_text:
                        text_parts.append(delta_text)
                        if on_text_delta is not None:
                            on_text_delta(delta_text)
                    continue

                if event_type == "response.reasoning_text.delta":
                    reasoning_delta = self._coerce_string(payload.get("delta"))
                    if reasoning_delta:
                        reasoning_parts.append(reasoning_delta)
                        if on_reasoning_delta is not None:
                            on_reasoning_delta(reasoning_delta)
                    continue

                if event_type == "response.function_call_arguments.delta":
                    for tool_delta in self._extract_response_stream_tool_call_delta(payload, tool_call_buffers):
                        if on_tool_call_delta is not None:
                            on_tool_call_delta(tool_delta)
                    continue

                if event_type == "response.function_call_arguments.done":
                    self._hydrate_response_stream_tool_call_from_done(payload, tool_call_buffers)
                    continue

                if event_type in {"response.output_item.added", "response.output_item.done"}:
                    self._capture_response_output_item(payload, tool_call_buffers, stream_output_items)
                    continue

                if event_type == "response.completed":
                    raw_response = payload.get("response")
                    if isinstance(raw_response, dict):
                        final_response = raw_response
                    continue

                if event_type in {"response.failed", "error"}:
                    raise RuntimeError(f"Responses API 流式请求失败: {json.dumps(payload, ensure_ascii=False)}")

            if final_response is not None:
                self._log_usage(final_response.get("usage"))
                return self._extract_responses_response(final_response)

            response_items = self._finalize_stream_response_items(stream_output_items, tool_call_buffers)
            return CompletionResponse(
                text="".join(text_parts).strip(),
                reasoning_text="".join(reasoning_parts).strip(),
                tool_calls=self._finalize_stream_tool_calls(tool_call_buffers),
                finish_reason=None,
                response_items=response_items,
            )

    def _build_request(
        self,
        messages: list[dict[str, object]],
        stream: bool,
        api_url: str,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> request.Request:
        if self._uses_responses_api(api_url):
            payload = self._build_responses_payload(
                messages=messages,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
            )
        else:
            payload = self._build_chat_completions_payload(
                messages=messages,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
            )
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "curl/8.4.0",
        }
        return request.Request(api_url, data=body, headers=headers, method="POST")

    def _build_chat_completions_payload(
        self,
        *,
        messages: list[dict[str, object]],
        stream: bool,
        tools: list[dict[str, object]] | None,
        tool_choice: str | dict[str, object] | None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.config.model,
            "temperature": 0.2,
            "messages": messages,
            "stream": stream,
        }
        if self.config.reasoning_effort:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if stream and self._is_deepseek_request():
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _build_responses_payload(
        self,
        *,
        messages: list[dict[str, object]],
        stream: bool,
        tools: list[dict[str, object]] | None,
        tool_choice: str | dict[str, object] | None,
    ) -> dict[str, object]:
        instructions, input_items = self._messages_to_responses_input(messages)
        payload: dict[str, object] = {
            "model": self.config.model,
            "temperature": 0.2,
            "input": input_items,
            "stream": stream,
            "include": ["reasoning.encrypted_content"],
        }
        if instructions:
            payload["instructions"] = instructions
        if self.config.reasoning_effort:
            payload["reasoning"] = {"effort": self.config.reasoning_effort}
        if tools:
            payload["tools"] = self._convert_tools_to_responses_tools(tools)
            payload["tool_choice"] = self._convert_tool_choice(tool_choice or "auto")
        return payload

    def _messages_to_responses_input(
        self,
        messages: list[dict[str, object]],
    ) -> tuple[str, list[dict[str, object]]]:
        instructions_parts: list[str] = []
        input_items: list[dict[str, object]] = []
        for message in messages:
            role = str(message.get("role", "")).strip().lower()
            if not role:
                continue

            if role == "system":
                content = self._flatten_content(message.get("content")).strip()
                if content:
                    instructions_parts.append(content)
                continue

            if role == "tool":
                tool_call_id = str(message.get("tool_call_id") or message.get("id") or "").strip()
                if not tool_call_id:
                    continue
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call_id,
                        "output": self._stringify_message_content(message.get("content")),
                    }
                )
                continue

            if role not in {"user", "assistant", "developer"}:
                continue

            raw_response_output_items = message.get("response_output_items")
            if role == "assistant" and isinstance(raw_response_output_items, list):
                for item in raw_response_output_items:
                    if isinstance(item, dict):
                        input_items.append(self._deep_clone_dict(item))
                continue

            content = self._flatten_content(message.get("content")).strip()
            if content:
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": content,
                    }
                )

            if role != "assistant":
                continue

            raw_tool_calls = message.get("tool_calls")
            if not isinstance(raw_tool_calls, list):
                continue
            for item in raw_tool_calls:
                if not isinstance(item, dict):
                    continue
                function = item.get("function")
                if not isinstance(function, dict):
                    continue
                name = str(function.get("name", "")).strip()
                if not name:
                    continue
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": str(item.get("id") or f"tool-call-{len(input_items)}"),
                        "name": name,
                        "arguments": self._stringify_message_content(function.get("arguments")),
                    }
                )

        return ("\n\n".join(instructions_parts).strip(), input_items)

    def _convert_tools_to_responses_tools(
        self,
        tools: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        converted: list[dict[str, object]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function")
            if not isinstance(function, dict):
                continue
            name = str(function.get("name", "")).strip()
            if not name:
                continue
            converted.append(
                {
                    "type": "function",
                    "name": name,
                    "description": str(function.get("description", "")).strip(),
                    "parameters": function.get("parameters") if isinstance(function.get("parameters"), dict) else {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                    "strict": False,
                }
            )
        return converted

    def _convert_tool_choice(
        self,
        tool_choice: str | dict[str, object],
    ) -> str | dict[str, object]:
        if isinstance(tool_choice, str):
            return tool_choice
        if not isinstance(tool_choice, dict):
            return "auto"
        function = tool_choice.get("function")
        if isinstance(function, dict):
            name = str(function.get("name", "")).strip()
            if name:
                return {"type": "function", "name": name}
        return tool_choice

    def _send_chat_request(
        self,
        messages: list[dict[str, object]],
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

    def _send_responses_request(
        self,
        messages: list[dict[str, object]],
        stream: bool,
        tools: list[dict[str, object]] | None = None,
        tool_choice: str | dict[str, object] | None = None,
    ) -> str:
        api_url = f"{self.config.base_url}/responses"
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
        return CompletionResponse(
            text=text,
            reasoning_text=reasoning_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )

    def _extract_responses_response(self, data: dict[str, object]) -> CompletionResponse:
        raw_output = data.get("output", [])
        output_items = [self._deep_clone_dict(item) for item in raw_output if isinstance(item, dict)]
        text = self._coerce_string(data.get("output_text")).strip()
        if not text:
            text = self._flatten_response_output_text(output_items).strip()
        reasoning_text = self._flatten_response_reasoning_text(output_items).strip()
        tool_calls = self._extract_response_tool_calls(output_items)
        status = data.get("status")
        return CompletionResponse(
            text=text,
            reasoning_text=reasoning_text,
            tool_calls=tool_calls,
            finish_reason=status if isinstance(status, str) else None,
            response_items=output_items,
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

    def _extract_response_tool_calls(
        self,
        output_items: list[dict[str, object]],
    ) -> list[CompletionToolCall]:
        tool_calls: list[CompletionToolCall] = []
        for index, item in enumerate(output_items):
            if str(item.get("type") or "").strip() != "function_call":
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            arguments = item.get("arguments", "")
            tool_calls.append(
                CompletionToolCall(
                    id=str(item.get("call_id") or item.get("id") or f"tool-call-{index}"),
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
                {"id": None, "name": None, "arguments_parts": []},
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

    def _extract_response_stream_tool_call_delta(
        self,
        payload: dict[str, object],
        tool_call_buffers: dict[int, dict[str, Any]],
    ) -> list[CompletionToolCallDelta]:
        raw_index = payload.get("output_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = len(tool_call_buffers)
        buffer = tool_call_buffers.setdefault(
            index,
            {"id": None, "name": None, "arguments_parts": []},
        )
        item_id = self._coerce_string(payload.get("item_id"))
        if item_id:
            buffer.setdefault("item_id", item_id)
        delta_text = self._coerce_string(payload.get("delta"))
        if delta_text:
            buffer["arguments_parts"].append(delta_text)
        return [
            CompletionToolCallDelta(
                index=index,
                id=self._coerce_string(buffer.get("id")) or self._coerce_string(buffer.get("item_id")),
                name=self._coerce_string(buffer.get("name")),
                arguments_delta=delta_text,
                arguments="".join(buffer.get("arguments_parts", [])),
            )
        ]

    def _hydrate_response_stream_tool_call_from_done(
        self,
        payload: dict[str, object],
        tool_call_buffers: dict[int, dict[str, Any]],
    ) -> None:
        raw_index = payload.get("output_index")
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        buffer = tool_call_buffers.setdefault(
            index,
            {"id": None, "name": None, "arguments_parts": []},
        )
        name = self._coerce_string(payload.get("name"))
        if name:
            buffer["name"] = name
        call_id = self._coerce_string(payload.get("call_id"))
        if call_id:
            buffer["id"] = call_id
        arguments = self._coerce_string(payload.get("arguments"))
        if arguments and not buffer.get("arguments_parts"):
            buffer["arguments_parts"] = [arguments]

    def _capture_response_output_item(
        self,
        payload: dict[str, object],
        tool_call_buffers: dict[int, dict[str, Any]],
        stream_output_items: dict[int, dict[str, Any]],
    ) -> None:
        raw_item = payload.get("item")
        if not isinstance(raw_item, dict):
            return
        raw_output_index = payload.get("output_index")
        try:
            output_index = int(raw_output_index)
        except (TypeError, ValueError):
            output_index = len(stream_output_items)
        item = self._deep_clone_dict(raw_item)
        stream_output_items[output_index] = item
        if str(item.get("type") or "").strip() != "function_call":
            return
        buffer = tool_call_buffers.setdefault(
            output_index,
            {"id": None, "name": None, "arguments_parts": []},
        )
        call_id = self._coerce_string(item.get("call_id")) or self._coerce_string(item.get("id"))
        if call_id:
            buffer["id"] = call_id
        name = self._coerce_string(item.get("name"))
        if name:
            buffer["name"] = name
        arguments = self._coerce_string(item.get("arguments"))
        if arguments and not buffer.get("arguments_parts"):
            buffer["arguments_parts"] = [arguments]

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

    def _finalize_stream_response_items(
        self,
        stream_output_items: dict[int, dict[str, Any]],
        tool_call_buffers: dict[int, dict[str, Any]],
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for index in sorted(stream_output_items):
            item = self._deep_clone_dict(stream_output_items[index])
            if str(item.get("type") or "").strip() == "function_call":
                buffer = tool_call_buffers.get(index)
                if buffer is not None:
                    item["call_id"] = self._coerce_string(buffer.get("id")) or self._coerce_string(item.get("call_id")) or self._coerce_string(item.get("id"))
                    if self._coerce_string(buffer.get("name")):
                        item["name"] = self._coerce_string(buffer.get("name"))
                    if buffer.get("arguments_parts"):
                        item["arguments"] = "".join(buffer.get("arguments_parts", []))
            items.append(item)
        seen_indexes = {
            index
            for index, item in stream_output_items.items()
            if str(item.get("type") or "").strip() == "function_call"
        }
        for index in sorted(tool_call_buffers):
            if index in seen_indexes:
                continue
            buffer = tool_call_buffers[index]
            name = self._coerce_string(buffer.get("name"))
            if not name:
                continue
            items.append(
                {
                    "type": "function_call",
                    "call_id": self._coerce_string(buffer.get("id")) or self._coerce_string(buffer.get("item_id")) or f"tool-call-{index}",
                    "name": name,
                    "arguments": "".join(buffer.get("arguments_parts", [])),
                }
            )
        return items

    def _log_usage(self, usage: object) -> None:
        normalized_usage = self._normalize_usage(usage)
        self.last_usage = normalized_usage
        if normalized_usage is None:
            return

        prompt_tokens = normalized_usage.get("inputTokens")
        completion_tokens = normalized_usage.get("outputTokens")
        hit_tokens = normalized_usage.get("cachedInputTokens")
        miss_tokens = max((prompt_tokens or 0) - (hit_tokens or 0), 0)

        extra_parts: list[str] = []
        if isinstance(prompt_tokens, int):
            extra_parts.append(f"prompt_tokens={prompt_tokens}")
        if isinstance(completion_tokens, int):
            extra_parts.append(f"completion_tokens={completion_tokens}")
        reasoning_tokens = normalized_usage.get("reasoningTokens")
        if isinstance(reasoning_tokens, int) and reasoning_tokens > 0:
            extra_parts.append(f"reasoning_tokens={reasoning_tokens}")
        if isinstance(hit_tokens, int):
            extra_parts.append(f"cache_hit={hit_tokens}")
        if isinstance(miss_tokens, int):
            extra_parts.append(f"cache_miss={miss_tokens}")
        if isinstance(hit_tokens, int) and isinstance(miss_tokens, int) and (hit_tokens + miss_tokens) > 0:
            hit_rate = hit_tokens / (hit_tokens + miss_tokens)
            extra_parts.append(f"cache_hit_rate={hit_rate:.1%}")
        logger.info("LLM usage: %s", ", ".join(extra_parts))

    def _normalize_usage(self, usage: object) -> dict[str, int] | None:
        if not isinstance(usage, dict):
            return None
        prompt_tokens = self._coerce_int(usage.get("prompt_tokens"))
        if prompt_tokens is None:
            prompt_tokens = self._coerce_int(usage.get("input_tokens"))
        completion_tokens = self._coerce_int(usage.get("completion_tokens"))
        if completion_tokens is None:
            completion_tokens = self._coerce_int(usage.get("output_tokens"))
        reasoning_tokens = self._coerce_int(usage.get("reasoning_tokens"))
        if reasoning_tokens is None:
            reasoning_tokens = self._coerce_nested_int(
                usage,
                ("completion_tokens_details", "reasoning_tokens"),
                ("output_tokens_details", "reasoning_tokens"),
            )
        cached_input_tokens = self._coerce_int(usage.get("prompt_cache_hit_tokens"))
        if cached_input_tokens is None:
            cached_input_tokens = self._coerce_nested_int(
                usage,
                ("prompt_tokens_details", "cached_tokens"),
                ("input_tokens_details", "cached_tokens"),
            )
        total_tokens = self._coerce_int(usage.get("total_tokens"))
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens
        if not any(
            value is not None
            for value in (
                prompt_tokens,
                completion_tokens,
                reasoning_tokens,
                cached_input_tokens,
                total_tokens,
            )
        ):
            return None
        return {
            "inputTokens": max(prompt_tokens or 0, 0),
            "outputTokens": max(completion_tokens or 0, 0),
            "reasoningTokens": max(reasoning_tokens or 0, 0),
            "cachedInputTokens": max(cached_input_tokens or 0, 0),
            "totalTokens": max(total_tokens or 0, 0),
        }

    def _coerce_int(self, value: object) -> int | None:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        return None

    def _coerce_nested_int(
        self,
        payload: dict[str, object],
        *paths: tuple[str, str],
    ) -> int | None:
        for parent_key, child_key in paths:
            parent = payload.get(parent_key)
            if not isinstance(parent, dict):
                continue
            coerced = self._coerce_int(parent.get(child_key))
            if coerced is not None:
                return coerced
        return None

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

    def _flatten_response_output_text(self, output_items: list[dict[str, object]]) -> str:
        parts: list[str] = []
        for item in output_items:
            if str(item.get("type") or "").strip() != "message":
                continue
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = str(block.get("type") or "").strip()
                if block_type not in {"output_text", "text", "input_text"}:
                    continue
                text = self._coerce_string(block.get("text"))
                if text:
                    parts.append(text)
        return "".join(parts)

    def _flatten_response_reasoning_text(self, output_items: list[dict[str, object]]) -> str:
        parts: list[str] = []
        for item in output_items:
            if str(item.get("type") or "").strip() != "reasoning":
                continue
            summary = item.get("summary")
            if isinstance(summary, list):
                for block in summary:
                    if isinstance(block, dict):
                        text = self._coerce_string(block.get("text"))
                        if text:
                            parts.append(text)
            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = self._coerce_string(block.get("text"))
                        if text:
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

    def _completion_has_content(self, completion: CompletionResponse) -> bool:
        return bool(completion.text.strip() or completion.tool_calls)

    def _max_attempts(self) -> int:
        return max(1, int(getattr(self.config, "max_retries", 10)) + 1)

    def _retry_delay_seconds(self, attempt: int) -> float:
        return float(2**attempt)

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(self._retry_delay_seconds(attempt))

    def _emit_retry_notice(
        self,
        on_reasoning_delta: Callable[[str], None] | None,
        *,
        attempt: int,
        attempts: int,
        error_message: str,
    ) -> None:
        if on_reasoning_delta is None:
            return
        retry_number = attempt + 1
        max_retries = max(0, attempts - 1)
        if retry_number > max_retries:
            return
        delay = self._retry_delay_seconds(attempt)
        compact_error = " ".join(error_message.split())
        if len(compact_error) > 800:
            compact_error = f"{compact_error[:800].rstrip()}..."
        on_reasoning_delta(
            "\n\n"
            f"请求出错：{compact_error}\n"
            f"正在重试（{retry_number}/{max_retries}），等待 {_format_retry_delay(delay)}。"
            "\n\n"
        )

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

    def _is_deepseek_request(self) -> bool:
        model_lower = self.config.model.lower()
        base_url_lower = self.config.base_url.lower()
        return "deepseek" in model_lower or "deepseek" in base_url_lower

    def _uses_responses_api(self, api_url: str | None = None) -> bool:
        if api_url is not None:
            return api_url.rstrip("/").endswith("/responses")
        return str(getattr(self.config, "api_mode", "chat_completions")).strip().lower() == "responses"

    def _stringify_message_content(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            flattened = self._flatten_content(value)
            if flattened:
                return flattened
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _coerce_string(self, value: object) -> str:
        return value if isinstance(value, str) else ""

    def _deep_clone_dict(self, value: dict[str, object]) -> dict[str, object]:
        return json.loads(json.dumps(value, ensure_ascii=False))
