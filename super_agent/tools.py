from __future__ import annotations

from typing import Any

from plan_agent.tools import PlanQuestions, ask_plan_questions
from zonix.tools import ToolContext


async def ask_user(
    ctx: ToolContext,
    questions: PlanQuestions,
    title: str = "需要确认一些需求细节",
    message: str = "请先回答下面几个关键问题，我会据此继续推进。",
) -> dict[str, Any]:
    """向用户发起澄清问题，适合存在关键偏好、取舍或缺失信息时使用。"""

    return await ask_plan_questions(
        ctx,
        questions=questions,
        title=title,
        message=message,
    )
