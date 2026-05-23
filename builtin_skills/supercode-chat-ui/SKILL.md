---
name: supercode-chat-ui
description: 修改 SuperCode 的聊天 UI、composer、mention 菜单、ai-elements 集成与交互细节。Use when the task touches frontend/src/App.tsx, frontend/src/components/app/*, frontend/src/components/ai-elements/*, or chat/message rendering behavior.
---

# SuperCode Chat UI

Use this skill when the request is about the web UI, chat layout, message rendering, composer behavior, mention menus, tool cards, terminal panel, context drawer, or web preview interactions.

## Mental Model

- `frontend/src/App.tsx` owns session state, stream state, selected workspace, terminal data, and request plumbing.
- `frontend/src/components/app/chat-panel.tsx` is the orchestration layer for chat UI, mention suggestion aggregation, and action toolbars.
- `frontend/src/components/app/chat-composer-editor.tsx` owns the TipTap-based rich composer and mention insertion behavior.
- `frontend/src/components/ai-elements/*` contains presentational primitives that should be reused before inventing parallel UI components.

## Working Rules

- Prefer extending existing ai-elements or app components over adding one-off widgets.
- Keep mention token compatibility stable. Current serialized format is `@[value]`.
- When adding a new mention kind, update both `chat-panel.tsx` and `chat-composer-editor.tsx`.
- Preserve current session streaming semantics from `App.tsx`; UI changes should not silently change backend request shapes.
- Keep changes mobile-safe and avoid introducing layout shifts in the composer area.

## Validation

- Do not run `pnpm build`.
- Prefer `pnpm exec tsc --noEmit` and targeted `pnpm exec eslint <file>` when frontend validation is needed.
