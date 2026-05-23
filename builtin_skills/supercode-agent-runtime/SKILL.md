---
name: supercode-agent-runtime
description: 处理 SuperCode 的 FastAPI 会话运行时、agent 路由、SSE 流、工具生命周期与模型状态同步。Use when the task touches fastapi_app/*, agent/*, coding_agent/*, plan_agent/*, or deploy_agent/*.
---

# SuperCode Agent Runtime

Use this skill when the task involves chat session lifecycle, agent selection, request routing, system prompt assembly, tool execution, confirmations, streaming events, or persisted session state.

## Mental Model

- `fastapi_app/main.py` is the runtime hub for sessions, API routes, SSE streaming, agent construction, and UI-facing state snapshots.
- `agent/*` provides the generic turn loop, brain interface, schema, and chat session abstraction.
- `coding_agent/*`, `plan_agent/*`, and `deploy_agent/*` layer specialized prompts and tools on top of the shared runtime.
- `fastapi_app/session_history.py` and `session_persistence.py` bridge live runtime state with UI history and restore behavior.

## Working Rules

- Prefer adding structured state to session snapshots or `state.data` instead of smuggling control signals through plain chat text.
- If a feature must persist across tool confirmations or `continue_turn`, store it on chat session state, not only in the HTTP handler local scope.
- When changing API payloads, update both backend Pydantic models and frontend TypeScript types in the same change set.
- Keep demo mode behavior intact when the real agent runtime is unavailable.

## Validation

- Prefer targeted Python tests with `conda activate base` and `python -m pytest <test file>`.
- Keep changes incremental in `fastapi_app/main.py`; that file already carries multiple responsibilities.
