---
name: safe-refactoring
description: Safe refactor planning and execution for cleanup, architecture, duplication, extraction, migration, 重构, 架构, 抽象, 迁移.
---

# Safe Refactoring

Use this skill when the user asks to refactor, simplify, extract abstractions, improve architecture, migrate code, or reduce duplication.

## Principles

- Preserve behavior unless the user explicitly asks for behavior changes.
- Read the existing style and ownership boundaries before editing.
- Prefer small vertical changes that can be reviewed and tested independently.
- Add abstractions only when they remove real complexity or match an established local pattern.

## Workflow

1. Map current behavior and callers.
2. Identify the smallest useful refactor slice.
3. Add or confirm a behavior-preserving test or smoke check.
4. Move code in a way that keeps names, imports, and public contracts stable.
5. Re-run focused checks after each slice.
6. Stop when the requested improvement is achieved; leave unrelated cleanup alone.

## Watchouts

- Do not mix formatting churn with logic movement.
- Do not rename public APIs casually.
- Do not hide complex coupling behind a vague helper name.
