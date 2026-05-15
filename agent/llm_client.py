from __future__ import annotations

import json
from urllib import error, request

from .config import AgentLLMConfig


class OpenAICompatibleClient:
    """一个极简的 OpenAI 兼容接口客户端。

    这里刻意只实现 demo 当前需要的能力：
    发送消息，拿回文本，再交给 brain 解析成下一步动作。
    """

    def __init__(self, config: AgentLLMConfig) -> None:
        self.config = config

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """向模型发送一轮对话并返回文本内容。"""

        payload = {
            "model": self.config.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        api_url = f"{self.config.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        http_request = request.Request(api_url, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(http_request, timeout=self.config.timeout) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"模型接口请求失败: HTTP {exc.code} - {error_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"模型接口连接失败: {exc.reason}") from exc

        data = json.loads(response_body)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("模型接口返回中没有 `choices` 字段内容。")

        message = choices[0].get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("模型接口没有返回可用文本内容。")
        return content.strip()
