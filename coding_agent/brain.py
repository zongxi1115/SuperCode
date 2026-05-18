from __future__ import annotations

import json
import platform
from pathlib import Path

from agent.llm_brain import OpenAICompatibleBrain
from agent.llm_client import OpenAICompatibleClient
from agent.schema import AgentState, StepRecord


MAX_CONVERSATION_MESSAGES = 12
MAX_RUNTIME_STATE_CHARS = 2_000
MAX_TOOL_RECORDS_IN_CONTEXT = 40
MAX_PLANNING_RECORDS_IN_CONTEXT = 20
TOOL_RECORD_VALUE_LIMIT = 4_000
PLANNING_RECORD_VALUE_LIMIT = 1_200


class CodingPromptBrain(OpenAICompatibleBrain):
    """基于编码提示词的专用 brain。"""

    def __init__(
        self,
        client: OpenAICompatibleClient,
        prompt_path: str | Path | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        super().__init__(client)
        self.prompt_path = Path(prompt_path) if prompt_path is not None else self._default_prompt_path()
        self.workspace = str(workspace) if workspace is not None else None

    def _build_system_prompt(
        self,
        tool_definitions: dict[str, dict[str, object]],
        response_mode: str = "legacy_json",
    ) -> str:
        base_prompt = self.prompt_path.read_text(encoding="utf-8").strip()
        tool_lines = [
            f"- {tool_name}: {str(metadata.get('description', '')).strip()}"
            for tool_name, metadata in tool_definitions.items()
        ]
        system_info = self._build_system_info()

        if response_mode == "native_tools":
            protocol_lines = [
                "## 输出协议",
                "当前接口已启用原生 tool calling。",
                "如果需要调用工具，必须使用原生 tool calling，不要在文本里输出 action/tool_name/tool_arguments JSON。",
                "如果不需要调用工具，直接输出给用户的最终答复文本。",
                "规则：",
                "1. 多个互不依赖的只读探索动作可以一次返回多个 tool calls，让系统并行执行。",
                "2. 写文件、替换内容、删除文件、执行命令默认一次只调用一个，避免互相影响。",
                "3. 调用工具时，参数名必须与工具参数定义保持一致。",
                "4. 在真正修改文件前，优先先探索相关目录、文件和引用关系。",
                "5. 普通答疑可以直接输出最终文本；需要查看或修改项目时再调用工具。",
                "6. 命令执行工具优先使用 `excecute`；如果输出里提到 `execute`，可视为同义工具。调用时必须提供 `content` 和 `timeout`（秒），并可选传 `terminal_id`。",
                "7. 如果 execute/excecute 返回的结果里 `status` 是 `running` 且 `awaiting_input` 为 true，说明命令很可能在等输入，应根据输出调用 `terminal_input`。如果结果里带有 `terminal_id`，后续继续交互时要沿用同一个 `terminal_id`。",
                "8. 如果 execute/excecute 返回的结果里 `status` 是 `running` 且 `awaiting_input` 为 false，说明命令大概率仍在后台执行，应调用 `terminal_wait` 继续等待。多个活动终端并存时，必须显式传 `terminal_id`。",
                "9. 如果用户目标已经完成，必须直接输出最终答复，不要为了“继续”而调用无必要工具。",
                "10. 已成功完成的工具调用会出现在内部工具调用记录里，不要重复同一工具调用；刚刚 write_file 创建的新文件内容以调用参数为准，不要立刻 read_file 回读。",
            ]
        else:
            protocol_lines = [
                "## 输出协议",
                "你必须始终只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。",
                (
                    'JSON 格式：{"action":"tool 或 final","thought":"当前思路",'
                    '"tool_name":"工具名","tool_arguments":{},'
                    '"tool_calls":[{"tool_name":"工具名","tool_arguments":{}}],'
                    '"final_answer":"最终答复"}'
                ),
                "规则：",
                "1. 如果 action 是 tool，优先使用 tool_calls 数组；只调用一个工具时也可使用 tool_name 和 tool_arguments。",
                "2. 多个互不依赖的只读探索动作可以合并进同一个 tool_calls，让系统并行执行。",
                "3. 写文件、替换内容、执行命令默认一次只调用一个，避免互相影响。",
                "4. 如果 action 是 final，必须提供 final_answer。",
                "5. 在真正修改文件前，优先先探索相关目录、文件和引用关系。",
                "6. 普通答疑可以直接 final；需要查看或修改项目时再调用工具。",
                "7. 命令执行工具优先使用 `excecute`；如果输出里提到 `execute`，可视为同义工具。调用时必须提供 `content` 和 `timeout`（秒），并可选传 `terminal_id`。",
                "8. 如果 execute/excecute 返回的结果里 `status` 是 `running` 且 `awaiting_input` 为 true，说明命令很可能在等输入，应根据输出调用 `terminal_input`。如果结果里带有 `terminal_id`，后续继续交互时要沿用同一个 `terminal_id`。",
                "9. 如果 execute/excecute 返回的结果里 `status` 是 `running` 且 `awaiting_input` 为 false，说明命令大概率仍在后台执行，应调用 `terminal_wait` 继续等待。多个活动终端并存时，必须显式传 `terminal_id`。",
                "10. 如果用户目标已经完成，必须 action=final，不要为了“继续”而调用无必要工具。",
                "11. 已成功完成的工具调用会出现在内部工具调用记录里，不要重复同一工具调用；刚刚 write_file 创建的新文件内容以调用参数为准，不要立刻 read_file 回读。",
            ]

        return "\n\n".join(
            [
                base_prompt,
                system_info,
                "## 当前工具注册表",
                "\n".join(tool_lines),
                "\n".join(protocol_lines),
            ]
        )

    def _build_messages(
        self,
        state: AgentState,
        tool_definitions: dict[str, dict[str, object]],
        response_mode: str = "legacy_json",
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt(tool_definitions, response_mode=response_mode)}
        ]

        previous_messages, latest_user_message = self._split_latest_user_message(state)
        messages.extend(self._conversation_messages_for_model(previous_messages))

        runtime_state_context = self._build_runtime_state_context(state)
        if runtime_state_context:
            messages.append({"role": "assistant", "content": runtime_state_context})

        planning_records_context = self._build_planning_records_context(state)
        if planning_records_context:
            messages.append({"role": "assistant", "content": planning_records_context})

        tool_records_context = self._build_tool_records_context(state)
        if tool_records_context:
            messages.append({"role": "assistant", "content": tool_records_context})

        if latest_user_message:
            messages.append({"role": "user", "content": latest_user_message})
        elif state.current_input.strip():
            messages.append({"role": "user", "content": state.current_input.strip()})

        current_turn_history = self._build_current_turn_history(state)
        if current_turn_history:
            messages.append(
                {
                    "role": "assistant",
                    "content": current_turn_history,
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": self._build_continuation_instruction(response_mode),
                }
            )

        return messages

    def _build_runtime_state_context(self, state: AgentState) -> str:
        raw_runtime_state = state.data.get("runtime_state")
        if not isinstance(raw_runtime_state, dict) or not raw_runtime_state:
            return ""

        serialized = json.dumps(raw_runtime_state, ensure_ascii=False)
        serialized = serialized.strip()
        if len(serialized) > MAX_RUNTIME_STATE_CHARS:
            serialized = f"{serialized[:MAX_RUNTIME_STATE_CHARS].rstrip()}... [truncated]"

        return "\n".join(
            [
                "[内部会话状态] 以下是后端维护的真实会话状态，不是新的用户请求。",
                "优先依据这里的 phase 和 deploy_state 判断是否已连接、是否正在等待用户输入，不要重新猜测。",
                serialized,
            ]
        )

    def _build_continuation_instruction(self, response_mode: str) -> str:
        if response_mode == "native_tools":
            return (
                "请基于当前轮已完成的工具调用和工具输出继续决策。"
                "不要重复已经完成且结果成功的工具调用。"
                "刚刚 write_file 创建的新文件内容已经在调用参数里，不要为了确认内容立刻 read_file。"
                "如果用户目标已经完成，直接输出最终答复，不要继续调用工具。"
                "如果还需要工具，请直接使用原生 tool calling；"
                "如果信息已经足够，直接输出给用户的最终答复文本。"
            )

        return (
            "请基于当前轮已完成的工具调用和工具输出，继续输出下一步决策 JSON。"
            "不要重复已经完成且结果成功的工具调用。"
            "刚刚 write_file 创建的新文件内容已经在调用参数里，不要为了确认内容立刻 read_file。"
            "如果用户目标已经完成，必须 action=final，不要继续调用工具。"
        )

    def _split_latest_user_message(self, state: AgentState) -> tuple[list[object], str]:
        messages = list(state.conversation_messages)
        current_input = state.current_input.strip()
        if not messages:
            return [], current_input

        last_message = messages[-1]
        last_role = str(getattr(last_message, "role", ""))
        last_content = str(getattr(last_message, "content", ""))
        if last_role == "user" and current_input and last_content.strip() == current_input:
            return messages[:-1], last_content
        return messages, current_input

    def _conversation_messages_for_model(self, raw_messages: list[object]) -> list[dict[str, str]]:
        model_messages: list[dict[str, str]] = []
        for message in raw_messages[-MAX_CONVERSATION_MESSAGES:]:
            role = str(getattr(message, "role", ""))
            content = str(getattr(message, "content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if content.startswith("[内部工具轨迹摘要]"):
                continue
            model_messages.append({"role": role, "content": content})
        return model_messages

    def _build_tool_records_context(self, state: AgentState) -> str:
        raw_records = state.data.get("tool_records", [])
        records = raw_records if isinstance(raw_records, list) else []
        raw_external_records = state.data.get("external_records", [])
        external_records = raw_external_records if isinstance(raw_external_records, list) else []
        current_turn_index = state.data.get("turn_index")
        historical_records = [
            record
            for record in records
            if not (
                isinstance(record, dict)
                and current_turn_index is not None
                and record.get("turn_index") == current_turn_index
            )
        ]
        if not historical_records and not external_records:
            return ""

        lines = [
            "[内部工具调用记录] 以下是真实工具调用记录，不是摘要，也不是新的用户请求。",
            "只用它判断哪些文件已经读取、写入、验证或确认；最终答复不要复读工具输出原文。",
        ]
        for index, record in enumerate(historical_records[-MAX_TOOL_RECORDS_IN_CONTEXT:], start=1):
            if isinstance(record, dict):
                lines.extend(self._format_tool_record(index, record))
        if external_records:
            lines.append("[内部确认记录]")
            for item in external_records[-20:]:
                text = str(item).strip()
                if text:
                    lines.append(f"- {text}")
        return "\n".join(lines)

    def _build_planning_records_context(self, state: AgentState) -> str:
        raw_records = state.data.get("planning_records", [])
        records = raw_records if isinstance(raw_records, list) else []
        current_turn_index = state.data.get("turn_index")
        historical_records = [
            record
            for record in records
            if not (
                isinstance(record, dict)
                and current_turn_index is not None
                and record.get("turn_index") == current_turn_index
            )
        ]
        if not historical_records:
            return ""

        lines = [
            "[内部规划记录] 以下是前面已经确定过的方案、约束和下一步意图，不是新的用户请求。",
            "继续执行时优先沿用这些结论；只有工具结果推翻它们时才重新规划。",
        ]
        for index, record in enumerate(historical_records[-MAX_PLANNING_RECORDS_IN_CONTEXT:], start=1):
            if not isinstance(record, dict):
                continue
            lines.extend(self._format_planning_record(index, record))
        return "\n".join(lines)

    def _format_planning_record(self, index: int, record: dict[str, object]) -> list[str]:
        lines = [f"规划 {index}:"]
        for label, key in (
            ("turn", "turn_index"),
            ("step", "step_index"),
            ("action", "action"),
        ):
            value = record.get(key)
            if value is not None and value != "":
                lines.append(f"- {label}: {value}")
        tools = record.get("tools")
        if tools:
            lines.append(f"- tools: {self._stringify_planning_value(tools)}")
        thought = record.get("thought")
        if thought:
            lines.append(f"- decided: {self._stringify_planning_value(thought)}")
        return lines

    def _stringify_planning_value(self, value: object) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = text.strip()
        if len(text) <= PLANNING_RECORD_VALUE_LIMIT:
            return text
        return f"{text[:PLANNING_RECORD_VALUE_LIMIT].rstrip()}... [truncated]"

    def _format_tool_record(self, index: int, record: dict[str, object]) -> list[str]:
        lines = [f"记录 {index}:"]
        for label, key in (
            ("id", "id"),
            ("turn", "turn_index"),
            ("step", "step_index"),
            ("tool", "name"),
            ("state", "state"),
            ("success", "success"),
        ):
            value = record.get(key)
            if value is not None and value != "":
                lines.append(f"- {label}: {value}")

        arguments = record.get("arguments")
        if arguments:
            lines.append(f"- arguments: {self._stringify_record_value(arguments)}")
        output = record.get("output")
        if output is not None and output != "":
            lines.append(f"- output: {self._stringify_record_value(output)}")
        error_message = record.get("error_message")
        if error_message:
            lines.append(f"- error: {self._stringify_record_value(error_message)}")
        return lines

    def _stringify_record_value(self, value: object) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = text.strip()
        if len(text) <= TOOL_RECORD_VALUE_LIMIT:
            return text
        return f"{text[:TOOL_RECORD_VALUE_LIMIT].rstrip()}... [truncated]"

    def _build_current_turn_history(self, state: AgentState) -> str:
        turn_index = state.data.get("turn_index")
        if turn_index is None:
            return ""

        step_records = state.data.get("step_records", [])
        if not isinstance(step_records, list):
            return ""

        current_turn_steps = [
            step
            for step in step_records
            if isinstance(step, StepRecord) and step.turn_index == turn_index
        ]
        if not current_turn_steps:
            return ""

        return "\n".join(
            [
                "[内部当前轮工具调用记录] 以下是本轮已经完成的真实工具调用记录，必须作为下一步决策依据。",
                self._format_history(
                    current_turn_steps,
                    include_thoughts=True,
                ),
            ]
        )

    def _build_system_info(self) -> str:
        lines = [
            "## 系统环境信息",
            f"- 操作系统：{platform.system()} {platform.release()} ({platform.machine()})",
        ]
        if platform.system() == "Windows":
            lines.append(f"- 注意Powershell分隔请使用分号")
        if self.workspace:
            lines.append(f"- 工作区路径：{self.workspace}")
        return "\n".join(lines)

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "coding.md"
