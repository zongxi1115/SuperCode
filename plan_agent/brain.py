from __future__ import annotations

from pathlib import Path

from coding_agent.brain import CodingPromptBrain


class PlanPromptBrain(CodingPromptBrain):
    """基于计划提示词的专用 brain。"""

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
                "1. 你的职责是需求澄清、方案调研和生成可编辑计划，不要直接写代码、执行命令或修改文件。",
                "2. 本地项目调研只允许使用只读工具；先看目录、再 grep、再按需 read_file。",
                "3. 当需求仍然模糊、缺少关键产品决策或存在多条明显分叉时，优先调用 ask_plan_questions。",
                "4. ask_plan_questions 只允许 single_choice、multi_choice、short_text 三种题型。",
                "5. 选择题请给出 2 到 5 个 AI 建议选项，不要自己额外生成“其他，请输入”，前端会追加这个选项。",
                "6. 能从用户描述或代码库高置信度推断的内容，不要重复提问。",
                "7. 需要外部信息时，先 search_web，再按需 fetch_url_content 精读候选网页。",
                "8. 多个互不依赖的只读探索动作可以并行；ask_plan_questions 和 save_plan 一次只调用一个。",
                "9. 当计划已经足够清晰时，必须调用 save_plan，把结构化草案保存到后端，然后再给用户总结。",
                "10. 如果 runtime_state.plan_state 里已经有 draft，用户又提出修改意见，应基于该 draft 更新，而不是重新从零规划。",
                "11. 最终答复要明确告诉用户：可以继续对话修改计划，或提交计划进入编码模式。",
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
                "1. 你的职责是需求澄清、方案调研和生成可编辑计划，不要直接写代码、执行命令或修改文件。",
                "2. 本地项目调研只允许使用只读工具；先看目录、再 grep、再按需 read_file。",
                "3. 当需求仍然模糊、缺少关键产品决策或存在多条明显分叉时，优先调用 ask_plan_questions。",
                "4. ask_plan_questions 只允许 single_choice、multi_choice、short_text 三种题型。",
                "5. 选择题请给出 2 到 5 个 AI 建议选项，不要自己额外生成“其他，请输入”，前端会追加这个选项。",
                "6. 能从用户描述或代码库高置信度推断的内容，不要重复提问。",
                "7. 需要外部信息时，先 search_web，再按需 fetch_url_content 精读候选网页。",
                "8. 多个互不依赖的只读探索动作可以放进同一个 tool_calls；ask_plan_questions 和 save_plan 一次只调用一个。",
                "9. 当计划已经足够清晰时，必须调用 save_plan，把结构化草案保存到后端，然后再给用户总结。",
                "10. 如果 runtime_state.plan_state 里已经有 draft，用户又提出修改意见，应基于该 draft 更新，而不是重新从零规划。",
                "11. 如果 action 是 final，必须提供 final_answer。",
                "12. 最终答复要明确告诉用户：可以继续对话修改计划，或提交计划进入编码模式。",
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

    def _build_continuation_instruction(self, response_mode: str) -> str:
        if response_mode == "native_tools":
            return (
                "请基于当前轮已完成的工具调用、工具输出和 runtime_state.plan_state 继续决策。"
                "如果用户刚刚补充了问题答案，要吸收这些答案继续完善计划。"
                "如果计划已经成熟，请调用 save_plan 更新草案；"
                "如果信息已经足够，也可以直接输出给用户的总结文本。"
            )

        return (
            "请基于当前轮已完成的工具调用、工具输出和 runtime_state.plan_state，"
            "继续输出下一步决策 JSON。"
            "如果用户刚刚补充了问题答案，要吸收这些答案继续完善计划。"
            "如果计划已经成熟，请调用 save_plan 更新草案。"
        )

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "plan.md"
