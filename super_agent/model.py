from __future__ import annotations

from pathlib import Path

from coding_agent.model import CodingPromptModel


class SuperPromptModel(CodingPromptModel):
    """Coding-compatible prompt model for 超能模式."""

    def _default_prompt_path(self) -> Path:
        return Path(__file__).resolve().parent / "prompts" / "super.md"
