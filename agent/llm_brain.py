from __future__ import annotations

import json

from .brain import AgentBrain, BrainDecision
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
    ) -> BrainDecision:
        """调用真实模型，决定下一步动作。"""

        system_prompt = self._build_system_prompt(tool_descriptions)
        user_prompt = self._build_user_prompt(state)
        raw_output = self.client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
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
                '{"action":"tool 或 final","thought":"你的当前思路","tool_name":"工具名","tool_arguments":{},"final_answer":"最终答案"}',
                "规则：",
                "1. 如果 action 是 tool，必须提供 tool_name 和 tool_arguments。",
                "2. 如果 action 是 final，必须提供 final_answer。",
                "3. 优先使用最少但足够的步骤完成任务。",
                "4. 调用工具时，参数名必须与该工具说明保持一致。",
                "5. 如果还不了解项目结构，先调用目录或文件浏览类工具。",
                "6. 这是一个对话式助手，必须结合历史上下文回答用户的追问。",
                "7. 如果用户只是普通提问，不一定要调用工具，可以直接 final。",
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
            if step.tool_result:
                lines.append(f"步骤 {step.index} 工具是否成功：{step.tool_result.success}")
                if step.tool_result.success:
                    lines.append(
                        f"步骤 {step.index} 工具输出："
                        f"{self._shrink_text(step.tool_result.output)}"
                    )
                else:
                    lines.append(
                        f"步骤 {step.index} 工具错误：{step.tool_result.error_message}"
                    )
            if step.final_answer:
                lines.append(f"步骤 {step.index} 最终答复：{step.final_answer}")
        return "\n".join(lines)

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

    def _to_decision(self, payload: dict[str, object]) -> BrainDecision:
        """把 JSON 结构转换成框架里的决策对象。"""

        action = str(payload.get("action", "")).strip().lower()
        thought = str(payload.get("thought", "")).strip() or "模型未提供思路。"

        if action == "tool":
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
