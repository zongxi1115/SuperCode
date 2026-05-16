from __future__ import annotations

import json
import logging
from collections.abc import Callable
from urllib import error, request

from .config import AgentLLMConfig

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """一个极简的 OpenAI 兼容接口客户端。

    这里刻意只实现 demo 当前需要的能力：
    发送消息，拿回文本，再交给 brain 解析成下一步动作。
    """

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

        try:
            response_body = self._send_chat_request(messages=messages, stream=False)
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"模型接口连接失败: {exc.reason}") from exc

        data = json.loads(response_body)
        self._log_usage(data.get("usage"))
        return self._extract_chat_response_text(data)

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        """以 OpenAI 兼容 SSE 方式流式获取文本。

        如果对端不支持流式接口，会自动回退到普通请求，并把完整文本一次性回调出去。
        """

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

        try:
            api_url = f"{self.config.base_url}/chat/completions"
            http_request = self._build_request(
                messages=messages,
                stream=True,
                api_url=api_url,
            )
            with request.urlopen(http_request, timeout=self.config.timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type.lower():
                    response_body = response.read().decode("utf-8")
                    data = json.loads(response_body)
                    self._log_usage(data.get("usage"))
                    text = self._extract_chat_response_text(data)
                    if text and on_delta is not None:
                        on_delta(text)
                    return text

                parts: list[str] = []
                last_usage: object | None = None
                for event_text in self._iter_sse_events(response):
                    if event_text == "[DONE]":
                        break

                    payload = json.loads(event_text)
                    usage = payload.get("usage")
                    if usage is not None:
                        last_usage = usage
                    delta_text = self._extract_stream_text(payload)
                    if not delta_text:
                        continue

                    parts.append(delta_text)
                    if on_delta is not None:
                        on_delta(delta_text)

                text = "".join(parts).strip()
                if not text:
                    raise RuntimeError("模型流式接口没有返回可用文本内容。")
                self._log_usage(last_usage)
                return text
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if self._should_fallback_to_non_stream(exc.code, error_body):
                text = self.chat_messages(messages)
                if text and on_delta is not None:
                    on_delta(text)
                return text
            raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"模型接口连接失败: {exc.reason}") from exc

    def _build_request(
        self,
        messages: list[dict[str, str]],
        stream: bool,
        api_url: str,
    ) -> request.Request:
        payload = {
            "model": self.config.model,
            "temperature": 0.2,
            "messages": messages,
            "stream": stream,
        }
        if stream and self._is_deepseek_request():
            payload["stream_options"] = {"include_usage": True}
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        return request.Request(api_url, data=body, headers=headers, method="POST")

    def _send_chat_request(
        self,
        messages: list[dict[str, str]],
        stream: bool,
    ) -> str:
        api_url = f"{self.config.base_url}/chat/completions"
        http_request = self._build_request(
            messages=messages,
            stream=stream,
            api_url=api_url,
        )
        with request.urlopen(http_request, timeout=self.config.timeout) as response:
            return response.read().decode("utf-8")

    def _extract_chat_response_text(self, data: dict[str, object]) -> str:
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("模型接口返回中没有 `choices` 字段内容。")

        message = choices[0].get("message", {})
        content = self._flatten_content(message.get("content"))
        if not content.strip():
            content = self._flatten_content(choices[0].get("text"))
        if not content.strip():
            raise RuntimeError("模型接口没有返回可用文本内容。")
        return content.strip()

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
