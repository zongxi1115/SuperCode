import tempfile
import unittest
from pathlib import Path

from fastapi_app.skills import (
    extract_skill_references_from_message,
    list_available_skills,
    resolve_message_skills,
    select_relevant_skills,
    strip_skill_mentions,
)


class SkillsRegistryTests(unittest.TestCase):
    def test_list_available_skills_includes_workspace_skill(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-skills-")).resolve()
        skill_dir = workspace / ".agents" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: demo-skill",
                    "description: Demo workspace skill",
                    "---",
                    "",
                    "# Demo Skill",
                    "",
                    "Keep the change small.",
                ]
            ),
            encoding="utf-8",
        )

        skills = list_available_skills(workspace)

        self.assertTrue(any(skill.id == "demo-skill" for skill in skills))
        self.assertTrue(any(skill.id == "supercode-chat-ui" for skill in skills))

    def test_strip_skill_mentions_keeps_other_mentions(self) -> None:
        message = "请用 @[skill:demo-skill] 看一下 @[src/App.tsx] 的输入区域"

        cleaned = strip_skill_mentions(message)

        self.assertEqual(cleaned, "请用 看一下 @[src/App.tsx] 的输入区域")

    def test_resolve_message_skills_uses_requested_ids_and_message_tokens(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-skills-")).resolve()
        skill_dir = workspace / ".agents" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    "name: demo-skill",
                    "description: Demo workspace skill",
                    "---",
                    "",
                    "Keep the change small.",
                ]
            ),
            encoding="utf-8",
        )

        cleaned, active_skills = resolve_message_skills(
            workspace,
            "请先 @[skill:demo-skill] 再处理这个页面",
            requested_skill_ids=["supercode-safe-validation"],
        )

        self.assertEqual(cleaned, "请先 再处理这个页面")
        self.assertEqual(
            [skill["id"] for skill in active_skills],
            ["supercode-safe-validation", "demo-skill"],
        )
        self.assertIn("Keep the change small.", active_skills[1]["content"])

    def test_extract_skill_references_from_message_dedicated_to_skill_tokens(self) -> None:
        message = "使用 @[skill:supercode-chat-ui] 和 @[src/App.tsx]，再参考 @[skill:demo-skill]"

        references = extract_skill_references_from_message(message)

        self.assertEqual(references, ["supercode-chat-ui", "demo-skill"])

    def test_select_relevant_skills_can_auto_match_by_description(self) -> None:
        workspace = Path(tempfile.mkdtemp(prefix="supercode-skills-")).resolve()

        selected = select_relevant_skills(workspace, "帮我调整聊天框的 composer 和 mention 交互")

        self.assertTrue(any(skill["id"] == "supercode-chat-ui" for skill in selected))
        matched = next(skill for skill in selected if skill["id"] == "supercode-chat-ui")
        self.assertEqual(matched["activationSource"], "auto")
        self.assertIn("terms:", matched["matchReason"])


if __name__ == "__main__":
    unittest.main()
