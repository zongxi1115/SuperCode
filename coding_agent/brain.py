from __future__ import annotations

from pathlib import Path

from agent.llm_brain import OpenAICompatibleBrain
from agent.llm_client import OpenAICompatibleClient


class CodingPromptBrain(OpenAICompatibleBrain):
    """基于编码提示词的专用 brain。"""

    def __init__(
        self,
        client: OpenAICompatibleClient,
        prompt_path: str | Path | None = None,
    ) -> None:
        super().__init__(client)
        self.prompt_path = Path(prompt_path) if prompt_path is not None else self._default_prompt_path()

    def _build_system_prompt(self, tool_descriptions: dict[str, str]) -> str:
        """加载 coding prompt，并补充当前可用工具说明和输出协议。"""

        base_prompt = self.prompt_path.read_text(encoding="utf-8").strip()
        tool_lines = [f"- {tool_name}: {description}" for tool_name, description in tool_descriptions.items()]

        return "\n\n".join(
            [
                base_prompt,
                "## 当前工具注册表",
                "\n".join(tool_lines),
                "\n".join(
                    [
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
                        "7. 命令执行工具优先使用 `excecute`；如果输出里提到 `execute`，可视为同义工具。调用时必须提供 `content` 和 `timeout`（秒）。",
                    ]
                ),
            ]
        )

    def _default_prompt_path(self) -> Path:
        """返回默认提示词路径。"""

        return Path(__file__).resolve().parent / "prompts" / "coding.md"
