from __future__ import annotations

import json
from typing import Any
from collections.abc import Callable

from .brain import AgentBrain, BrainDecision, BrainStreamingUpdate
from .llm_client import OpenAICompatibleClient
from .schema import AgentState, ConversationMessage, StepRecord


class OpenAICompatibleBrain(AgentBrain):
    """基于真实模型接口的 brain。

    它通过提示词要求模型输出严格 JSON，再把 JSON 解析成下一步动作。
    整体结构仍然保持简单，方便你之后替换成更强的规划或工具调用协议。
    """

    def __init__(self, client: OpenAICompatibleClient) -> None:
        self.client = client

    def decide(
        self,
        state: AgentState,
        tool_descriptions: dict[str, str],
        on_stream: Callable[[BrainStreamingUpdate], None] | None = None,
    ) -> BrainDecision:
        """调用真实模型，决定下一步动作。"""

        system_prompt = self._build_system_prompt(tool_descriptions)
        user_prompt = self._build_user_prompt(state)
        if on_stream is None:
            raw_output = self.client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        else:
            raw_chunks: list[str] = []

            def handle_delta(delta: str) -> None:
                raw_chunks.append(delta)
                current_output = "".join(raw_chunks)
                on_stream(
                    BrainStreamingUpdate(
                        raw_output=current_output,
                        action=self._extract_partial_string_field(current_output, "action"),
                        thought=self._extract_partial_string_field(current_output, "thought"),
                        tool_name=self._extract_partial_string_field(current_output, "tool_name"),
                        final_answer=self._extract_partial_string_field(current_output, "final_answer"),
                    )
                )

            raw_output = self.client.chat_stream(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                on_delta=handle_delta,
            )
        payload = self._parse_json_output(raw_output)
        return self._to_decision(payload)

    def _build_system_prompt(self, tool_descriptions: dict[str, str]) -> str:
        """构造系统提示词。"""

        tool_lines = []
        for tool_name, description in tool_descriptions.items():
            tool_lines.append(f"- {tool_name}: {description}")

        return "\n".join(
            [
                "你是一个支持多轮对话的编码智能体大脑，负责决定下一步要调用哪个工具，或者直接给出最终答案。",
                "你必须始终只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。",
                "可用工具如下：",
                *tool_lines,
                "输出 JSON 格式如下：",
                (
                    '{"action":"tool 或 final","thought":"你的当前思路",'
                    '"tool_name":"工具名","tool_arguments":{},'
                    '"tool_calls":[{"tool_name":"工具名","tool_arguments":{}}],'
                    '"final_answer":"最终答案"}'
                ),
                "规则：",
                "1. 如果 action 是 tool，优先提供 tool_calls 数组；只调用一个工具时也可退回 tool_name 和 tool_arguments。",
                "2. 如果 action 是 final，必须提供 final_answer。",
                "3. 多个互不依赖的只读探索动作可以放进同一个 tool_calls 里并行执行，例如同时读取多个文件或同时做多个搜索。",
                "4. 涉及写文件、替换内容或执行命令时，除非你非常确定互不影响，否则一次只调用一个工具。",
                "5. 优先使用最少但足够的步骤完成任务。",
                "6. 调用工具时，参数名必须与该工具说明保持一致。",
                "7. 如果还不了解项目结构，先调用目录或文件浏览类工具。",
                "8. 这是一个对话式助手，必须结合历史上下文回答用户的追问。",
                "9. 如果用户只是普通提问，不一定要调用工具，可以直接 final。",
            ]
        )

    def _build_user_prompt(self, state: AgentState) -> str:
        """构造用户提示词。"""

        step_records = state.data.get("step_records", [])
        conversation_text = self._format_conversation(state.conversation_messages)
        history_text = self._format_history(step_records)

        return "\n".join(
            [
                f"会话总目标：{state.task}",
                "",
                "对话历史：",
                conversation_text,
                "",
                f"用户本轮最新问题：{state.current_input}",
                "",
                "当前这一轮已执行步骤：",
                history_text,
                "",
                "请基于当前信息输出下一步决策 JSON。",
            ]
        )

    def _format_conversation(self, messages: list[ConversationMessage], limit: int = 12) -> str:
        """格式化最近的多轮对话历史。"""

        if not messages:
            return "暂无对话历史。"

        recent_messages = messages[-limit:]
        lines: list[str] = []
        for message in recent_messages:
            role_name = "用户" if message.role == "user" else "助手"
            lines.append(f"{role_name}: {message.content}")
        return "\n".join(lines)

    def _format_history(self, step_records: list[StepRecord]) -> str:
        """把历史步骤压缩成适合喂给模型的文本。"""

        if not step_records:
            return "暂无历史步骤。"

        lines: list[str] = []
        for step in step_records:
            lines.append(f"步骤 {step.index} 思考：{step.thought}")
            if step.tool_call:
                lines.append(
                    f"步骤 {step.index} 工具调用：{step.tool_call.name} "
                    f"{json.dumps(step.tool_call.arguments, ensure_ascii=False)}"
                )
            extra_tool_calls = step.tool_calls if step.tool_calls else []
            if step.tool_call and extra_tool_calls:
                extra_tool_calls = extra_tool_calls[1:]
            if extra_tool_calls:
                for tool_call in extra_tool_calls:
                    lines.append(
                        f"步骤 {step.index} 工具调用：{tool_call.name} "
                        f"{json.dumps(tool_call.arguments, ensure_ascii=False)}"
                    )

            if step.tool_result:
                lines.extend(self._format_tool_result_lines(step.index, step.tool_result))

            extra_tool_results = step.tool_results if step.tool_results else []
            if step.tool_result and extra_tool_results:
                extra_tool_results = extra_tool_results[1:]
            if extra_tool_results:
                for tool_result in extra_tool_results:
                    lines.extend(self._format_tool_result_lines(step.index, tool_result))
            if step.final_answer:
                lines.append(f"步骤 {step.index} 最终答复：{step.final_answer}")
        return "\n".join(lines)

    def _format_tool_result_lines(self, step_index: int, tool_result: Any) -> list[str]:
        """格式化单个工具结果。"""

        lines = [f"步骤 {step_index} 工具是否成功：{tool_result.success}"]
        if tool_result.success:
            lines.append(
                f"步骤 {step_index} 工具输出："
                f"{self._shrink_text(tool_result.output)}"
            )
        else:
            lines.append(f"步骤 {step_index} 工具错误：{tool_result.error_message}")
        return lines

    def _shrink_text(self, value: object, limit: int = 1600) -> str:
        """压缩工具输出，避免上下文膨胀太快。"""

        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _parse_json_output(self, raw_output: str) -> dict[str, object]:
        """解析模型返回的 JSON 文本。"""

        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"模型返回不是合法 JSON 对象: {raw_output}")

        json_text = cleaned[start : end + 1]
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"模型返回 JSON 解析失败: {raw_output}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"模型返回的 JSON 根节点必须是对象: {raw_output}")
        return payload

    def _extract_partial_string_field(self, text: str, field_name: str) -> str | None:
        marker = f'"{field_name}"'
        start = text.find(marker)
        if start == -1:
            return None

        colon_index = text.find(":", start + len(marker))
        if colon_index == -1:
            return None

        cursor = colon_index + 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != '"':
            return None

        cursor += 1
        buffer: list[str] = []
        escape = False
        unicode_digits: str | None = None

        while cursor < len(text):
            char = text[cursor]

            if unicode_digits is not None:
                if char.lower() in "0123456789abcdef":
                    unicode_digits += char
                    if len(unicode_digits) == 4:
                        buffer.append(chr(int(unicode_digits, 16)))
                        unicode_digits = None
                        escape = False
                else:
                    unicode_digits = None
                    escape = False
                cursor += 1
                continue

            if escape:
                mapped = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "b": "\b",
                    "f": "\f",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }.get(char)
                if mapped is not None:
                    buffer.append(mapped)
                    escape = False
                    cursor += 1
                    continue

                if char == "u":
                    unicode_digits = ""
                    cursor += 1
                    continue

                buffer.append(char)
                escape = False
                cursor += 1
                continue

            if char == "\\":
                escape = True
                cursor += 1
                continue

            if char == '"':
                return "".join(buffer)

            buffer.append(char)
            cursor += 1

        return "".join(buffer) if buffer else None

    def _to_decision(self, payload: dict[str, object]) -> BrainDecision:
        """把 JSON 结构转换成框架里的决策对象。"""

        action = str(payload.get("action", "")).strip().lower()
        thought = str(payload.get("thought", "")).strip() or "模型未提供思路。"

        if action == "tool":
            tool_calls = payload.get("tool_calls")
            if tool_calls is not None:
                if not isinstance(tool_calls, list) or not tool_calls:
                    raise ValueError("模型返回的 tool_calls 必须是非空数组。")

                normalized_calls: list[dict[str, Any]] = []
                for item in tool_calls:
                    if not isinstance(item, dict):
                        raise ValueError("tool_calls 中的每一项都必须是对象。")
                    tool_name = str(item.get("tool_name", "")).strip()
                    tool_arguments = item.get("tool_arguments", {})
                    if not tool_name:
                        raise ValueError("tool_calls 中存在缺少 tool_name 的项。")
                    if not isinstance(tool_arguments, dict):
                        raise ValueError("tool_calls 中的 tool_arguments 不是对象。")
                    normalized_calls.append(
                        {
                            "tool_name": tool_name,
                            "tool_arguments": tool_arguments,
                        }
                    )
                return BrainDecision.call_tools(thought=thought, tool_calls=normalized_calls)

            tool_name = str(payload.get("tool_name", "")).strip()
            tool_arguments = payload.get("tool_arguments", {})
            if not tool_name:
                raise ValueError("模型决定调用工具，但没有返回 tool_name。")
            if not isinstance(tool_arguments, dict):
                raise ValueError("模型返回的 tool_arguments 不是对象。")
            return BrainDecision.call_tool(
                thought=thought,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
            )

        if action == "final":
            final_answer = str(payload.get("final_answer", "")).strip()
            if not final_answer:
                raise ValueError("模型决定结束，但没有返回 final_answer。")
            return BrainDecision.finish(thought=thought, final_answer=final_answer)

        raise ValueError(f"模型返回了不支持的 action: {action}")
