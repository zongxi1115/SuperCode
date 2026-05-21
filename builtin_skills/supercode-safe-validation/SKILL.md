---
name: supercode-safe-validation
description: 使用 SuperCode 的安全验证流程：避免 pnpm build，优先 pnpm exec 检查，并在 Python 命令里使用 conda base。Use when the task needs local verification.
---

# SuperCode Safe Validation

Use this skill when you need to validate changes without disrupting the developer's running environment.

## Rules

- Do not run `pnpm build` unless the user explicitly allows it.
- Prefer `pnpm` over `npm`.
- For frontend or TypeScript validation, prefer:
  - `pnpm exec tsc --noEmit`
  - `pnpm exec eslint <target files>`
- For Python work, use the conda `base` environment.
- Prefer targeted tests over broad, expensive runs when the changed area is known.

## Good Defaults

- Validate only the files or test modules touched by the current change.
- If a full verification step is risky or unavailable, explain what was checked and what remains for the user to run manually.
