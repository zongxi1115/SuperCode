from __future__ import annotations

import json
import platform
from pathlib import Path

from agent.openai_model import OpenAICompatibleModel
from agent.llm_client import OpenAICompatibleClient
from agent.schema import AgentState, StepRecord, ToolResult
from zonix.models.base import ModelRequest


MAX_CONVERSATION_MESSAGES = 12
MAX_RUNTIME_STATE_CHARS = 2_000
MAX_TOOL_RECORDS_IN_CONTEXT = 40
MAX_PLANNING_RECORDS_IN_CONTEXT = 20
TOOL_RECORD_VALUE_LIMIT = 4_000
PLANNING_RECORD_VALUE_LIMIT = 1_200
MAX_ACTIVE_SKILL_CONTENT_CHARS = 8_000
MAX_AVAILABLE_SKILL_DESCRIPTION_CHARS = 280

HTML_ARTIFACT_OUTPUT_RULES = [
    "## 最终答复 HTML Artifact 规则",
    "1. 默认最终答复使用 Markdown；仅当 runtime_state.final_answer_rendering == \"html\"，且最终答复明显适合可视化、交互卡片、小工具、报告面板或独立预览内容时，才在 Markdown 正文中自然插入 artifact。",
    "2. Artifact 是最终答复里的临时渲染块，不是项目文件，不会写入工作区；不要把它说成已创建文件、已保存网页或已修改代码。",
    "3. 如果用户明确要求创建/修改项目里的 HTML、页面、组件或静态文件，在具备改文件能力的编码场景必须使用写文件/改文件工具完成；完成后最终答复可以可选附带 artifact 作为预览，但不能用 artifact 代替文件修改。计划/部署等非本地改文件场景应先说明后续需要的文件变更，而不是伪称 artifact 已保存。",
    "4. 如果只是解释、总结、展示交互示例、数据看板、一次性 demo 或可视化结果，可以只给 artifact，不要主动创建文件。",
    "5. Artifact block 格式必须是：<supercode-artifact type=\"html\" title=\"短标题\">\\n<!doctype html>...\\n</supercode-artifact>。",
    "6. HTML 应尽量自包含；允许为可视化/交互使用少量常见 HTTPS CDN 第三方库（如 Chart.js、D3、Three.js、Tailwind CDN），但只在确有价值时使用，并在正文简短说明用了哪些外部库。",
    "7. 不要访问 window.parent / window.top，不要跳转父页面，不要读取本地文件、密钥或尝试持久化到工作区；artifact 内代码只服务于预览本身。",
    "8. 对话内用于回答问题的 HTML artifact 默认不要设置整页背景色、满屏渐变或 body 深色背景；优先透明背景，让内容自然嵌入聊天正文。只有用户明确要求海报、落地页、沉浸式页面或独立视觉作品时才使用明显背景。",
    "9. 对话内用于回答问题的 HTML artifact 应尽量自然高度完整展示，避免固定 100vh、高度滚动容器、overflow:auto/scroll 或需要内部滚动条的布局；宽度默认适配聊天正文即可。",
    "10. 不要把普通文字总结强行改写成 HTML；正文和 artifact 可以混排，artifact 只承载值得独立渲染的内容。",
]


class CodingPromptModel(OpenAICompatibleModel):
    """Model adapter with coding-specific prompts and context."""

    def __init__(
        self,
        client: OpenAICompatibleClient,
        prompt_path: str | Path | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        super().__init__(client)
        self.prompt_path = Path(prompt_path) if prompt_path is not None else self._default_prompt_path()
        self.workspace = str(workspace) if workspace is not None else None

    def build_prompt_chain(
        self,
        tool_definitions: dict[str, dict[str, object]],
    ) -> list[str]:
        return [
            self._build_base_prompt(),
            self._build_system_info(),
            self.build_tool_registry_prompt(tool_definitions),
            self.build_native_protocol_prompt(),
        ]

    def build_tool_registry_prompt(
        self,
        tool_definitions: dict[str, dict[str, object]],
    ) -> str:
        tool_lines = [
            f"- {tool_name}: {str(metadata.get('description', '')).strip()}"
            for tool_name, metadata in tool_definitions.items()
        ]
        return "\n".join(["## 当前工具注册表", *tool_lines])

    def build_native_protocol_prompt(self) -> str:
        return "\n".join(
            [
                "## 输出协议",
                "当模型请求携带原生 tools 时，必须使用原生 tool calling，不要在文本里输出 action/tool_name/tool_arguments JSON。",
                "如果不需要调用工具，直接输出给用户的最终答复文本。",
                "规则：",
                "1. 多个互不依赖的只读探索动作可以一次返回多个 tool calls，让系统并行执行。",
                "2. 写文件、替换内容、删除文件、执行命令默认一次只调用一个，避免互相影响。",
                "3. 调用工具时，参数名必须与工具参数定义保持一致。",
                "4. 在真正修改文件前，优先先探索相关目录、文件和引用关系。",
                "4.1 定位文件时优先使用 glob_file 和 grep_file，不要默认展开整个仓库。",
                "4.2 grep_file 优先先用 output_mode=files_with_matches 看命中分布，再按需用 output_mode=content。",
                "4.3 read_file 默认从文件开头读；返回会带 total_lines、total_chars 等元信息；如果工具提示已截断，必须继续用更小的 offset/limit 或 start_line/end_line 分段读取后续内容。",
                "4.4 编辑单个文件前，尽量一次性读完整个相关文件或足够大的连续范围；不要为了省一小段上下文反复 read_file。",
                "4.5 修改同一个文件时，优先把多处变更合并到一次 apply_patch 的 edits 里；除非工具报错或上下文不足，不要 patch 一次再读一次再 patch。",
                "5. 普通答疑可以直接输出最终文本；需要查看或修改项目时再调用工具。",
                "6. 普通短命令优先使用 `run_command(content, timeout)`；timeout 是硬边界，超时会终止进程树。",
                "7. 只有明确需要长期运行、等待用户介入、持续观察输出或交互输入时，才使用 `start_task(content, timeout, task_id?)`。返回的 `task_id` 后续必须沿用。",
                "8. 如果 start_task/task_wait 返回 `awaiting_input=true`，调用 `task_input`；如果仍在运行但不等输入，按需要调用 `task_wait`；需要停止时调用 `task_stop`。",
                "9. 如果用户目标已经完成，必须直接输出最终答复，不要为了“继续”而调用无必要工具。",
                "10. 已成功完成的工具调用会出现在内部工具调用记录里，不要重复同一工具调用；刚刚 write_file 创建的新文件内容以调用参数为准，不要立刻 read_file 回读。",
                "11. 当回复内容引用了 search_web 或 fetch_url_content 返回的来源时，必须在引用处使用 [[url]] 标注来源，url 填写工具返回的原始链接。例如：「该 API 支持流式响应[[https://docs.example.com/streaming]]」。不要对未经过工具验证的信息使用此标注。",
                "12. 你会在上下文里看到 [技能目录]，必要时应主动使用其中相关 skill 的描述与约束，不要等用户先显式 @ skill。",
                "13. 当用户明确表达可长期复用的偏好、工作流约束、交互风格或项目约定时，调用 remember_preference 记录；不要记录普通任务过程或临时事实。",
                "14. 当命令不存在、运行时/SDK/系统包缺失、PATH 未配置，或需要用 winget 搜索/安装系统包时，先调用 get_docs，参数 type=environment_setup，读取集中流程文档后再给用户渐进式提示。安装会改变用户机器环境，除非用户已明确要求执行，否则先展示将执行的命令并等待确认。",
                "15. 当需要让模型查看工作区里的图片时，调用 load_image_to_conversation；不要用 read_file 读取图片二进制。",
                *HTML_ARTIFACT_OUTPUT_RULES,
            ]
        )

    def build_legacy_protocol_prompt(self) -> str:
        return "\n".join(
            [
                "## JSON fallback 输出协议",
                "当前模型接口不可用原生 tool calling 时，你必须始终只输出一个 JSON 对象，不要输出 Markdown，不要输出解释。",
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
                "5.1 定位文件时优先使用 glob_file 和 grep_file，不要默认展开整个仓库。",
                "5.2 grep_file 优先先用 output_mode=files_with_matches 看命中分布，再按需用 output_mode=content。",
                "5.3 read_file 默认从文件开头读；返回会带 total_lines、total_chars 等元信息；如果工具提示已截断，必须继续用更小的 offset/limit 或 start_line/end_line 分段读取后续内容。",
                "5.4 编辑单个文件前，尽量一次性读完整个相关文件或足够大的连续范围；不要为了省一小段上下文反复 read_file。",
                "5.5 修改同一个文件时，优先把多处变更合并到一次 apply_patch 的 edits 里；除非工具报错或上下文不足，不要 patch 一次再读一次再 patch。",
                "6. 普通答疑可以直接 final；需要查看或修改项目时再调用工具。",
                "7. 普通短命令优先使用 `run_command(content, timeout)`；timeout 是硬边界，超时会终止进程树。",
                "8. 只有明确需要长期运行、等待用户介入、持续观察输出或交互输入时，才使用 `start_task(content, timeout, task_id?)`。返回的 `task_id` 后续必须沿用。",
                "9. 如果 start_task/task_wait 返回 `awaiting_input=true`，调用 `task_input`；如果仍在运行但不等输入，按需要调用 `task_wait`；需要停止时调用 `task_stop`。",
                "10. 如果用户目标已经完成，必须 action=final，不要为了“继续”而调用无必要工具。",
                "11. 已成功完成的工具调用会出现在内部工具调用记录里，不要重复同一工具调用；刚刚 write_file 创建的新文件内容以调用参数为准，不要立刻 read_file 回读。",
                "12. 你会在上下文里看到 [技能目录]，必要时应主动使用其中相关 skill 的描述与约束，不要等用户先显式 @ skill。",
                "13. 当用户明确表达可长期复用的偏好、工作流约束、交互风格或项目约定时，调用 remember_preference 记录；不要记录普通任务过程或临时事实。",
                "14. 当命令不存在、运行时/SDK/系统包缺失、PATH 未配置，或需要用 winget 搜索/安装系统包时，先调用 get_docs，参数 type=environment_setup，读取集中流程文档后再给用户渐进式提示。安装会改变用户机器环境，除非用户已明确要求执行，否则先展示将执行的命令并等待确认。",
                "15. 当需要让模型查看工作区里的图片时，调用 load_image_to_conversation；不要用 read_file 读取图片二进制。",
                *HTML_ARTIFACT_OUTPUT_RULES,
            ]
        )

    def build_runtime_context_prompt(self, ctx: object, task: object | None = None) -> str:
        state = getattr(ctx, "state", None)
        if not isinstance(state, AgentState):
            return ""

        system_content: list[str] = []
        for context in (
            self._build_runtime_state_context(state),
            self._build_long_term_memory_context(state),
            self._build_planning_records_context(state),
            self._build_tool_records_context(state),
            self._build_available_skills_context(state),
            self._build_active_skills_context(state),
        ):
            if context:
                system_content.append(context)
        return "\n\n".join(system_content)

    def _build_base_prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8").strip()

    def _build_system_prompt(
        self,
        tool_definitions: dict[str, dict[str, object]],
        response_mode: str = "legacy_json",
    ) -> str:
        prompts = self.build_prompt_chain(tool_definitions)
        prompts[-1] = (
            self.build_native_protocol_prompt()
            if response_mode == "native_tools"
            else self.build_legacy_protocol_prompt()
        )
        return "\n\n".join(prompt for prompt in prompts if prompt)

    def _build_legacy_protocol_prompt(
        self,
        tool_definitions: dict[str, dict[str, object]],
    ) -> str:
        return self.build_legacy_protocol_prompt()

    def _build_messages(
        self,
        request: ModelRequest,
        state: AgentState,
        tool_definitions: dict[str, dict[str, object]],
        response_mode: str = "legacy_json",
    ) -> list[dict[str, object]]:
        messages = super()._build_messages(
            request,
            state,
            tool_definitions,
            response_mode=response_mode,
        )
        if response_mode != "native_tools":
            current_turn_history = self._build_current_turn_history(state)
            if current_turn_history:
                messages.append(
                    {
                        "role": "user",
                        "content": "\n\n".join(
                            [
                                current_turn_history,
                                self._build_continuation_instruction(response_mode),
                            ]
                        ),
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

    def _build_long_term_memory_context(self, state: AgentState) -> str:
        raw_memory = state.data.get("long_term_memory")
        if not isinstance(raw_memory, str):
            return ""
        return raw_memory.strip()

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

    def _conversation_messages_for_model(self, raw_messages: list[object]) -> list[dict[str, object]]:
        model_messages: list[dict[str, object]] = []
        for message in raw_messages[-MAX_CONVERSATION_MESSAGES:]:
            role = str(getattr(message, "role", ""))
            content = str(getattr(message, "content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            if content.startswith("[内部工具轨迹摘要]"):
                continue
            model_message: dict[str, object] = {"role": role, "content": content}
            model_messages.append(model_message)
        return model_messages

    def _build_tool_records_context(self, state: AgentState) -> str:
        records = state.tool_records
        external_records = state.external_records
        current_turn_index = state.turn_index
        historical_records = [
            record
            for record in records
            if not (
                isinstance(record, dict)
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

    def _build_active_skills_context(self, state: AgentState) -> str:
        raw_skills = state.data.get("active_skills")
        skills = raw_skills if isinstance(raw_skills, list) else []
        if not skills:
            return ""

        lines = [
            "[已激活技能] 以下技能由用户显式 @ 选择，或由系统依据当前请求自动激活，用作当前任务的附加操作手册。",
            "如果技能与当前请求直接相关，优先遵循其中的工作流、约束和文件定位建议。",
            "如果技能内容与系统提示、工具约束或用户明确要求冲突，以更高优先级要求为准。",
            "不要向用户复述整份技能原文，也不要把它误当成新的用户请求。",
        ]

        for index, item in enumerate(skills, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or f"skill-{index}").strip()
            description = str(item.get("description") or "").strip()
            scope = str(item.get("scope") or "").strip()
            source_path = str(item.get("sourcePath") or "").strip()
            activation_source = str(item.get("activationSource") or "").strip()
            match_reason = str(item.get("matchReason") or "").strip()
            content = str(item.get("content") or "").strip()
            if len(content) > MAX_ACTIVE_SKILL_CONTENT_CHARS:
                content = f"{content[:MAX_ACTIVE_SKILL_CONTENT_CHARS].rstrip()}... [truncated]"

            lines.append(f"## 技能 {index}: {name}")
            if description:
                lines.append(f"说明: {description}")
            if activation_source:
                lines.append(f"激活方式: {activation_source}")
            if match_reason:
                lines.append(f"匹配依据: {match_reason}")
            if scope or source_path:
                source_bits = [part for part in [scope, source_path] if part]
                lines.append(f"来源: {' | '.join(source_bits)}")
            if content:
                lines.append(content)

        return "\n".join(lines)

    def _build_available_skills_context(self, state: AgentState) -> str:
        raw_skills = state.data.get("available_skills")
        skills = raw_skills if isinstance(raw_skills, list) else []
        if not skills:
            return ""

        lines = [
            "[技能目录] 以下是当前仓库可用技能的摘要目录。",
            "你应该主动查看这些技能说明，判断是否有适合当前任务的技能。",
            "即使用户没有显式 @ skill，也可以参考这些摘要来吸收相应工作流或约束。",
            "如果下方还出现了 [已激活技能]，优先遵循那些技能的完整正文。",
        ]

        for index, item in enumerate(skills, start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or f"skill-{index}").strip()
            description = str(item.get("description") or "").strip()
            scope = str(item.get("scope") or "").strip()
            if len(description) > MAX_AVAILABLE_SKILL_DESCRIPTION_CHARS:
                description = f"{description[:MAX_AVAILABLE_SKILL_DESCRIPTION_CHARS].rstrip()}..."
            lines.append(f"- {name} ({scope or 'unknown'}): {description or '无描述'}")

        return "\n".join(lines)

    def _build_planning_records_context(self, state: AgentState) -> str:
        records = state.planning_records
        current_turn_index = state.turn_index
        historical_records = [
            record
            for record in records
            if not (
                isinstance(record, dict)
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
        turn_index = state.turn_index
        if turn_index <= 0:
            return ""

        step_records = state.step_records

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

    def _build_current_turn_native_messages(self, state: AgentState) -> list[dict[str, object]]:
        turn_index = state.turn_index
        if turn_index <= 0:
            return []

        step_records = state.step_records

        current_turn_steps = [
            step
            for step in step_records
            if isinstance(step, StepRecord) and step.turn_index == turn_index
        ]
        if not current_turn_steps:
            return []

        messages: list[dict[str, object]] = []
        for step in current_turn_steps:
            raw_response_items = [
                json.loads(json.dumps(item, ensure_ascii=False))
                for item in step.provider_response_items
                if isinstance(item, dict)
            ]
            tool_calls = step.tool_calls or ([step.tool_call] if step.tool_call is not None else [])
            if not tool_calls and not raw_response_items:
                continue

            if raw_response_items:
                messages.append(
                    {
                        "role": "assistant",
                        "response_output_items": raw_response_items,
                    }
                )
            else:
                assistant_tool_calls = []
                for position, tool_call in enumerate(tool_calls, start=1):
                    if tool_call is None:
                        continue
                    tool_call_id = tool_call.id or f"step-{step.index}-tool-{position}-{tool_call.name}"
                    assistant_tool_calls.append(
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                            },
                        }
                    )

                if not assistant_tool_calls:
                    continue

                assistant_message: dict[str, object] = {
                    "role": "assistant",
                    "tool_calls": assistant_tool_calls,
                }
                reasoning_content = " ".join(step.thought.split()).strip()
                if reasoning_content:
                    assistant_message["reasoning_content"] = reasoning_content
                messages.append(assistant_message)

            tool_results = step.tool_results or ([step.tool_result] if step.tool_result is not None else [])
            results_by_id = {
                result.tool_call_id: result
                for result in tool_results
                if result is not None and result.tool_call_id
            }
            emitted_result_ids: set[str | None] = set()

            for tool_call in tool_calls:
                if tool_call is None:
                    continue
                tool_call_id = tool_call.id or ""
                result = results_by_id.get(tool_call_id)
                if result is None:
                    continue
                emitted_result_ids.add(result.tool_call_id)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": self._serialize_native_tool_result(result),
                    }
                )

            for result in tool_results:
                if result is None or result.tool_call_id in emitted_result_ids:
                    continue
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.tool_call_id or f"step-{step.index}-tool-result",
                        "content": self._serialize_native_tool_result(result),
                    }
                )

        return messages

    def _serialize_native_tool_result(self, result: ToolResult) -> str:
        output = result.output
        if result.success:
            return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)

        payload = {
            "success": False,
            "error": str(result.error_message or "Tool execution failed."),
        }
        if output is not None:
            payload["output"] = output
        return json.dumps(payload, ensure_ascii=False)

    def _build_system_info(self) -> str:
        lines = [
            "## 系统环境信息",
            f"- 操作系统：{platform.system()} {platform.release()} ({platform.machine()})",
        ]
        if platform.system() == "Windows":
            lines.append("- 注意Powershell分隔请使用分号")
        if self.workspace:
            lines.append(f"- 工作区路径：{self.workspace}")
        return "\n".join(lines)

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "coding.md"


class CodeExplorationPromptModel(CodingPromptModel):
    """Read-only code exploration model adapter."""

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "code_exploration.md"


# Compatibility aliases. New code should prefer *Model names.
