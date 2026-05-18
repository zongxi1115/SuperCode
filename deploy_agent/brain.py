from __future__ import annotations

from pathlib import Path

from coding_agent.brain import CodingPromptBrain


class DeployPromptBrain(CodingPromptBrain):
    """基于部署提示词的专用 brain。"""

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
                "1. 后端提供的内部会话状态是当前阶段的唯一真实来源；优先读取 phase 和 deploy_state，不要靠历史自行猜测。",
                "2. 在调用 list_files、read_file、transfer_files、execute 前，必须先确认已经拿到有效的 deploy session_id；如果没有，就先调用 connect。",
                "3. connect 会暂停当前轮并请求用户填写部署目标信息；恢复后要复用 connect 成功返回的 session_id，不要编造 session_id。",
                "4. list_files、read_file、transfer_files、execute 的第一个参数都必须是 session_id。",
                "5. access root 是当前任务允许访问的根路径，不固定等于应用目录；它可以是 /home/app、/etc/nginx、/etc/systemd/system、/var/log/nginx 或 /。",
                "6. 如果当前任务需要访问 access root 之外的目录，不要继续硬试；应明确说明当前 root 太窄，并给出建议的新 root，然后重新 connect。",
                "7. 远程 Linux 部署时，root_path 必须是服务器上的绝对路径；如果看到盘符或反斜杠，说明路径明显填错。",
                "8. 如果 root_path 明显是错误的本地 Windows 路径，必须停止继续调用 list_files/read_file/execute，并重新 connect；不要尝试传 '/' 或其他绝对路径跳出当前 root。",
                "9. 部署前优先探索目录结构和关键配置文件，再决定执行命令或传输文件。",
                "10. 可以并行做多个只读探索动作，例如同时 list_files 和 read_file；执行命令或传输文件时一次只调用一个写操作工具。",
                "11. 如果 read_file 内容过长，要改用 start_line / end_line 分段读取，不要硬读整大文件。",
                "12. transfer_files 的 path / file 都支持字符串和数组；如果需要同步多个目录或文件，优先合并到一次调用里。",
                "13. 如果 deploy_state 里有 active_extra_info，要优先把这些上下文用于判断候选目录、服务名、站点名和部署方式。",
                "14. password 属于敏感输入，不会出现在 runtime state；不要要求回显密码，也不要在最终答复里复述任何密码内容。",
                "15. 如果工具输出显示认证失败、Permission denied、EACCES、Operation not permitted、目录不存在，不要立刻重复同一个失败调用；先诊断用户、目录、权限或凭据问题。",
                "16. 当权限可疑时，优先使用只读诊断命令，例如 whoami、pwd、id、ls -ld <dir>，而不是直接重复部署命令。",
                "17. 对会改变线上状态的命令，要先在最终答复里说明目的、影响和验证方式，再执行。",
                "18. 如果用户目标已经完成，必须直接输出最终答复，不要为了“继续”而调用无必要工具。",
                "19. 已成功完成的工具调用会出现在内部工具调用记录里，不要重复同一连接或同一读取动作；连续失败的同一工具在没有新信息前也不要重试。",
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
                "1. 后端提供的内部会话状态是当前阶段的唯一真实来源；优先读取 phase 和 deploy_state，不要靠历史自行猜测。",
                "2. 在调用 list_files、read_file、transfer_files、execute 前，必须先确认已经拿到有效的 deploy session_id；如果没有，就先调用 connect。",
                "3. connect 会暂停当前轮并请求用户填写部署目标信息；恢复后要复用 connect 成功返回的 session_id，不要编造 session_id。",
                "4. list_files、read_file、transfer_files、execute 的第一个参数都必须是 session_id。",
                "5. access root 是当前任务允许访问的根路径，不固定等于应用目录；它可以是 /home/app、/etc/nginx、/etc/systemd/system、/var/log/nginx 或 /。",
                "6. 如果当前任务需要访问 access root 之外的目录，不要继续硬试；应明确说明当前 root 太窄，并给出建议的新 root，然后重新 connect。",
                "7. 远程 Linux 部署时，root_path 必须是服务器上的绝对路径；如果看到盘符或反斜杠，说明路径明显填错。",
                "8. 如果 root_path 明显是错误的本地 Windows 路径，必须停止继续调用 list_files/read_file/execute，并重新 connect；不要尝试传 '/' 或其他绝对路径跳出当前 root。",
                "9. 多个互不依赖的只读探索动作可以放进同一个 tool_calls；执行命令或传输文件时一次只调用一个写操作工具。",
                "10. 部署前优先探索目录结构和关键配置文件，再决定执行命令。",
                "11. 如果 action 是 final，必须提供 final_answer。",
                "12. 如果 read_file 内容过长，要改用 start_line / end_line 分段读取，不要硬读整大文件。",
                "13. transfer_files 的 path / file 都支持字符串和数组；如果需要同步多个目录或文件，优先合并到一次调用里。",
                "14. 如果 deploy_state 里有 active_extra_info，要优先把这些上下文用于判断候选目录、服务名、站点名和部署方式。",
                "15. password 属于敏感输入，不会出现在 runtime state；不要要求回显密码，也不要在最终答复里复述任何密码内容。",
                "16. 如果工具输出显示认证失败、Permission denied、EACCES、Operation not permitted、目录不存在，不要立刻重复同一个失败调用；先诊断用户、目录、权限或凭据问题。",
                "17. 当权限可疑时，优先使用只读诊断命令，例如 whoami、pwd、id、ls -ld <dir>，而不是直接重复部署命令。",
                "18. 对会改变线上状态的命令，要先在最终答复里说明目的、影响和验证方式，再执行。",
                "19. 如果用户目标已经完成，必须 action=final，不要继续调用无必要工具；连续失败的同一工具在没有新信息前也不要重试。",
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
                "请基于当前轮已完成的工具调用和工具输出继续决策。"
                "如果 connect 已返回成功结果，后续 list_files、read_file、execute 必须复用那个 session_id。"
                "不要重复已经完成且结果成功的 connect。"
                "如果用户目标已经完成，直接输出最终答复，不要继续调用工具。"
                "如果还需要工具，请继续使用原生 tool calling；"
                "如果信息已经足够，直接输出给用户的最终答复文本。"
            )

        return (
            "请基于当前轮已完成的工具调用和工具输出，继续输出下一步决策 JSON。"
            "如果 connect 已返回成功结果，后续 list_files、read_file、execute 必须复用那个 session_id。"
            "不要重复已经完成且结果成功的 connect。"
            "如果用户目标已经完成，必须 action=final，不要继续调用工具。"
        )

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "deploy.md"
