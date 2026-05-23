---
name: skill-authoring
description: Create, improve, and maintain SuperCode skills, SKILL.md files, frontmatter, triggers, skill descriptions, 技能, 内置技能.
---

# Skill Authoring

Use this skill when creating, editing, reviewing, or organizing SuperCode skills.

## SuperCode Skill Shape

- Built-in skills live in `builtin_skills/<skill-name>/SKILL.md`.
- Workspace skills live in `.agents/skills/<skill-name>/SKILL.md`.
- Each `SKILL.md` should start with YAML frontmatter containing `name` and `description`.
- The runtime slugifies `name` to produce the skill id, so keep `name` stable, lowercase, and kebab-cased.
- Put trigger words in `description`; the auto-selector scores the id, name, and description.

## Authoring Rules

- Make the skill self-contained. Do not depend on local scripts or reference files unless they are bundled with the skill.
- Keep the description short but searchable in both English and the user's likely language.
- Write actionable workflow guidance, not a general essay.
- Include guardrails that prevent common agent mistakes.
- Keep scope narrow enough that activation helps more than it distracts.

## Maintenance

After adding, removing, or renaming a built-in skill, update tests that assert specific skill ids or auto-selection behavior.
