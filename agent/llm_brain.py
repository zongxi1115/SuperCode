from __future__ import annotations

import json
from typing import Any
from collections.abc import Callable

from .brain import AgentBrain, BrainDecision, BrainStreamingUpdate
from .llm_client import (
    CompletionResponse,
    CompletionToolCall,
    CompletionToolCallDelta,
    OpenAICompatibleClient,
    UnsupportedToolCallingError,
)
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
        tool_definitions: dict[str, dict[str, Any]],
        on_stream: Callable[[BrainStreamingUpdate], None] | None = None,
    ) -> BrainDecision:
        """调用真实模型，决定下一步动作。"""
        native_messages = self._build_messages(state, tool_definitions, response_mode="native_tools")
        native_tools = self._build_native_tool_specs(tool_definitions)

        try:
            if on_stream is None:
                completion = self.client.chat_completion_messages(
                    native_messages,
                    tools=native_tools,
                )
            else:
                streamed_text = ""
                streamed_reasoning = ""

                def handle_text_delta(delta: str) -> None:
                    nonlocal streamed_text
                    streamed_text += delta
                    on_stream(
                        BrainStreamingUpdate(
                            raw_output=streamed_text,
                            action="final",
                            final_answer=streamed_text,
                        )
                    )

                def handle_reasoning_delta(delta: str) -> None:
                    nonlocal streamed_reasoning
                    streamed_reasoning += delta
                    on_stream(
                        BrainStreamingUpdate(
                            raw_output=streamed_reasoning,
                            thought=streamed_reasoning,
                        )
                    )

                def handle_tool_delta(delta_update: CompletionToolCallDelta) -> None:
                    tool_name = delta_update.name
                    streamed_tool_argument_name, streamed_tool_input = (
                        self._extract_partial_streamable_tool_input(
                            delta_update.arguments,
                            tool_name,
                        )
                    )
                    on_stream(
                        BrainStreamingUpdate(
                            raw_output=delta_update.arguments,
                            tool_name=tool_name,
                            streamed_tool_name=tool_name,
                            streamed_tool_argument_name=streamed_tool_argument_name,
                            streamed_tool_input=streamed_tool_input,
                        )
                    )

                completion = self.client.chat_stream_completion_messages(
                    native_messages,
                    tools=native_tools,
                    on_text_delta=handle_text_delta,
                    on_reasoning_delta=handle_reasoning_delta,
                    on_tool_call_delta=handle_tool_delta,
                )

            return self._completion_to_decision(completion)
        except UnsupportedToolCallingError:
            pass
        except ValueError as exc:
            if "既没有返回 tool_calls，也没有返回可用文本内容" not in str(exc):
                raise

        messages = self._build_messages(state, tool_definitions, response_mode="legacy_json")
        if on_stream is None:
            raw_output = self.client.chat_messages(messages)
        else:
            raw_chunks: list[str] = []

            def handle_delta(delta: str) -> None:
                raw_chunks.append(delta)
                current_output = "".join(raw_chunks)
                tool_name = self._extract_partial_string_field(current_output, "tool_name")
                streamed_tool_argument_name, streamed_tool_input = (
                    self._extract_partial_streamable_tool_input(current_output, tool_name)
                )
                on_stream(
                    BrainStreamingUpdate(
                        raw_output=current_output,
                        action=self._extract_partial_string_field(current_output, "action"),
                        thought=self._extract_partial_string_field(current_output, "thought"),
                        tool_name=tool_name,
                        final_answer=self._extract_partial_string_field(current_output, "final_answer"),
                        streamed_tool_name=tool_name,
                        streamed_tool_argument_name=streamed_tool_argument_name,
                        streamed_tool_input=streamed_tool_input,
                    )
                )

            raw_output = self.client.chat_stream_messages(messages, on_delta=handle_delta)
        payload = self._parse_json_output(raw_output)
        return self._to_decision(payload)

    def _build_messages(
        self,
        state: AgentState,
        tool_definitions: dict[str, dict[str, Any]],
        response_mode: str = "legacy_json",
    ) -> list[dict[str, str]]:
        system_prompt = self._build_system_prompt(tool_definitions, response_mode=response_mode)
        user_prompt = self._build_user_prompt(state)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_system_prompt(
        self,
        tool_definitions: dict[str, dict[str, Any]],
        response_mode: str = "legacy_json",
    ) -> str:
        """构造系统提示词。"""

        tool_lines = []
        for tool_name, metadata in tool_definitions.items():
            description = str(metadata.get("description", "")).strip()
            tool_lines.append(f"- {tool_name}: {description}")

        if response_mode == "native_tools":
            return "\n".join(
                [
                    "你是一个支持多轮对话的编码智能体大脑，负责决定下一步要调用哪个工具，或者直接给出最终答案。",
                    "当前接口已启用原生 tool calling。",
                    "如果需要调用工具，必须使用原生 tool calling，不要在文本内容里输出 JSON，不要解释将要调用什么。",
                    "如果不需要调用工具，直接输出给用户的最终答复文本。",
                    "可用工具如下：",
                    *tool_lines,
                    "规则：",
                    "1. 多个互不依赖的只读探索动作可以一次返回多个 tool calls 并行执行。",
                    "2. 涉及写文件、替换内容、删除文件或执行命令时，除非你非常确定互不影响，否则一次只调用一个工具。",
                    "3. 调用工具时，参数名必须与工具参数定义保持一致。",
                    "4. 如果还不了解项目结构，先调用目录或文件浏览类工具。",
                    "5. 这是一个对话式助手，必须结合历史上下文回答用户的追问。",
                ]
            )

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

    def _build_native_tool_specs(
        self,
        tool_definitions: dict[str, dict[str, Any]],
    ) -> list[dict[str, object]]:
        tool_specs: list[dict[str, object]] = []
        for tool_name, metadata in tool_definitions.items():
            description = str(metadata.get("description", "")).strip()
            parameters_schema = metadata.get("parameters_schema")
            if not isinstance(parameters_schema, dict):
                parameters_schema = {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                }
            tool_specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": description,
                        "parameters": parameters_schema,
                    },
                }
            )
        return tool_specs

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
            step_prefix = f"第 {step.turn_index} 轮 步骤 {step.index}"
            lines.append(f"{step_prefix} 思考：{step.thought}")
            if step.tool_call:
                lines.append(
                    f"{step_prefix} 工具调用：{step.tool_call.name} "
                    f"{json.dumps(step.tool_call.arguments, ensure_ascii=False)}"
                )
            extra_tool_calls = step.tool_calls if step.tool_calls else []
            if step.tool_call and extra_tool_calls:
                extra_tool_calls = extra_tool_calls[1:]
            if extra_tool_calls:
                for tool_call in extra_tool_calls:
                    lines.append(
                        f"{step_prefix} 工具调用：{tool_call.name} "
                        f"{json.dumps(tool_call.arguments, ensure_ascii=False)}"
                    )

            if step.tool_result:
                lines.extend(self._format_tool_result_lines(step_prefix, step.tool_result))

            extra_tool_results = step.tool_results if step.tool_results else []
            if step.tool_result and extra_tool_results:
                extra_tool_results = extra_tool_results[1:]
            if extra_tool_results:
                for tool_result in extra_tool_results:
                    lines.extend(self._format_tool_result_lines(step_prefix, tool_result))
            if step.final_answer:
                lines.append(f"{step_prefix} 最终答复：{step.final_answer}")
        return "\n".join(lines)

    def _format_tool_result_lines(self, step_prefix: str, tool_result: Any) -> list[str]:
        """格式化单个工具结果。"""

        lines = [f"{step_prefix} 工具是否成功：{tool_result.success}"]
        if tool_result.success:
            lines.append(
                f"{step_prefix} 工具输出："
                f"{self._stringify_tool_output(tool_result.output)}"
            )
        else:
            lines.append(f"{step_prefix} 工具错误：{tool_result.error_message}")
        return lines

    def _stringify_tool_output(self, value: object) -> str:
        """把工具输出稳定转成文本，不做静默截断。"""
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return text.strip()

    def _parse_json_output(self, raw_output: str) -> dict[str, object]:
        """解析模型返回的 JSON 文本。"""

        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        decoder = json.JSONDecoder()
        fallback_payload: dict[str, object] | None = None
        for start_index, char in enumerate(cleaned):
            if char != "{":
                continue

            try:
                payload, _ = decoder.raw_decode(cleaned[start_index:])
            except json.JSONDecodeError:
                continue

            if not isinstance(payload, dict):
                continue

            if self._looks_like_decision_payload(payload):
                return payload
            if fallback_payload is None:
                fallback_payload = payload

        if fallback_payload is not None:
            return fallback_payload

        raise ValueError(f"模型返回 JSON 解析失败: {raw_output}")

    def _looks_like_decision_payload(self, payload: dict[str, object]) -> bool:
        """判断一个对象是否像 agent 决策 JSON。"""

        action = str(payload.get("action", "")).strip().lower()
        if action in {"tool", "final"}:
            return True

        if "tool_calls" in payload or "tool_name" in payload or "tool" in payload:
            return True
        if "final_answer" in payload:
            return True
        return False

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

    def _extract_partial_streamable_tool_input(
        self,
        text: str,
        tool_name: str | None,
    ) -> tuple[str | None, str | None]:
        if tool_name == "write_file":
            content = self._extract_partial_string_field(text, "content")
            return ("content", content) if content is not None else (None, None)

        if tool_name == "apply_patch":
            patch_text = self._extract_partial_string_field(text, "patch")
            return ("patch", patch_text) if patch_text is not None else (None, None)

        if tool_name == "replace_file":
            new_content = self._extract_partial_string_field(text, "new_content")
            return ("new_content", new_content) if new_content is not None else (None, None)

        return None, None

    def _completion_to_decision(self, completion: CompletionResponse) -> BrainDecision:
        if completion.tool_calls:
            normalized_calls: list[dict[str, Any]] = []
            for tool_call in completion.tool_calls:
                normalized_calls.append(
                    {
                        "tool_name": tool_call.name,
                        "tool_arguments": self._parse_tool_arguments_text(
                            tool_call.arguments,
                            tool_call.name,
                        ),
                    }
                )
            return BrainDecision.call_tools(thought=completion.reasoning_text, tool_calls=normalized_calls)

        final_text = completion.text.strip()
        if final_text:
            return BrainDecision.finish(thought=completion.reasoning_text, final_answer=final_text)

        raise ValueError("模型接口既没有返回 tool_calls，也没有返回可用文本内容。")

    def _parse_tool_arguments_text(
        self,
        arguments_text: str,
        tool_name: str,
    ) -> dict[str, Any]:
        cleaned = arguments_text.strip()
        if not cleaned:
            return {}
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"工具 {tool_name} 的 arguments 不是合法 JSON：{arguments_text}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"工具 {tool_name} 的 arguments 必须是对象。")
        return parsed

    def _to_decision(self, payload: dict[str, object]) -> BrainDecision:
        """把 JSON 结构转换成框架里的决策对象。"""

        action = str(payload.get("action", "")).strip().lower()
        thought = str(payload.get("thought", "")).strip()

        if not action:
            if "tool_calls" in payload or "tool_name" in payload or "tool" in payload:
                action = "tool"
            elif "final_answer" in payload:
                action = "final"

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

            tool_name = str(payload.get("tool_name") or payload.get("tool") or "").strip()
            tool_arguments = payload.get("tool_arguments", payload.get("args", {}))
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

        raise ValueError(
            "模型返回了不支持的 action，且无法从 tool_name/tool_calls/final_answer 推断动作。"
        )
