from __future__ import annotations

import platform
from pathlib import Path

from agent.llm_brain import OpenAICompatibleBrain
from agent.llm_client import OpenAICompatibleClient
from agent.schema import AgentState, StepRecord


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

        if state.conversation_messages:
            messages.extend(
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in state.conversation_messages
            )
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
                    "content": "请基于当前轮已完成的工具调用和工具输出，继续输出下一步决策 JSON。不要重复已经完成且结果成功的工具调用。",
                }
            )

        return messages

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
                "[内部当前轮工具轨迹] 以下是本轮已经完成的步骤，必须作为下一步决策依据。",
                self._format_history(current_turn_steps),
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
