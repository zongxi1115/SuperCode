---
name: supercode-skills
description: 增强 SuperCode 的 skills 功能、skill 加载规则、@skill 集成与 skill 编写约定。Use when the task is about skills themselves.
---

# SuperCode Skills

Use this skill when the request is about designing, loading, activating, displaying, or authoring skills inside SuperCode.

## Current Convention

- Skills are directory-based.
- Each skill directory must contain a `SKILL.md`.
- `SKILL.md` should start with YAML frontmatter containing at least `name` and `description`.
- Workspace skills live under `.agents/skills/<skill-name>/SKILL.md`.
- Built-in skills can live in a separate app-owned skill root and should stay self-contained.

## Runtime Rules

- The chat composer can expose skills through `@` mention suggestions.
- Serialized mention tokens should stay machine-readable; prefer `@[skill:<id>]`.
- The backend should strip skill mention tokens from the user task before routing or prompting.
- Activated skills should be injected as current-turn guidance, not stored as fake user messages.
- If the same turn resumes after confirmation or extra input, the activated skills should still be available.

## Authoring Rules

- Keep skill descriptions short and specific so they work well in mention menus.
- Keep the main body actionable and self-contained.
- If a skill references other files, those files should be accessible from the relevant workspace or the skill should summarize the required guidance inline.
