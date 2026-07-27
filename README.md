<div align="center">

# SuperCode

**Your Local AI Software Engineer**

A local-first, multi-agent coding workspace that brings autonomous development capabilities to your desktop.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind_v4-38BDF8?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)](https://vitejs.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[English](#features) | [中文](#核心特性)

</div>

---

<!-- TODO: 添加一张主截图，展示完整工作界面（聊天面板 + 代码编辑器 + 终端）
     建议文件名: docs/images/hero.png
     尺寸建议: 1280x720 或更高 -->

## Features

**Three specialized agents** — Plan, Code, Deploy — orchestrated through a unified runtime. Each agent is a pluggable prompt model with its own toolset, sharing a common execution loop.

| | |
|---|---|
| Multi-Agent Runtime | Decoupled agent engine with `CodingAgent`, `PlanAgent`, `DeployAgent` — each with specialized tools and prompts |
| Live Thinking Stream | SSE-powered real-time visualization of chain-of-thought, tool calls, and terminal outputs |
| Parallel Tool Execution | Read-only tools (search, glob, read) run concurrently via thread pool — faster responses |
| @Skill System | Type `@` to inject project-scoped markdown rules, or let the AI auto-activate them |
| Monaco Editor | Full code editor with file tree, diff view, and git integration |
| Real Terminal | xterm.js + PTY backend for real shell interaction with wait/confirm safety |
| Kanban Board | Built-in task tracking with drag-and-drop, rich text descriptions |
| Plan Builder | Interactive Q&A planning with rich text plan editor before coding |
| OpenAI-Compatible | Works with any OpenAI-format API — GPT, DeepSeek, Qwen, local models |

<!-- TODO: 添加功能截图网格，每个特性配一张小图
     建议文件名: docs/images/features/ 目录下
     需要: chat-panel.png, terminal.png, editor.png, kanban.png, skills.png, plan.png -->

## Core Architecture

```
┌──────────────────────────────────────────────────┐
│                   Web Dashboard                   │
│     React 19 · Tailwind v4 · Monaco · xterm.js   │
└────────────────────┬─────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼─────────────────────────────┐
│                  FastAPI Server                    │
│           Session Store · Skills Registry          │
└──────┬──────────┬──────────┬──────────────────────┘
       │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐
  │ Plan   │ │ Coding │ │ Deploy │   Pluggable
  │ Agent  │ │ Agent  │ │ Agent  │   Prompt Models
  └────┬───┘ └───┬────┘ └──┬─────┘
       │         │         │
  ┌────▼─────────▼─────────▼─────┐
  │      Unified Agent Engine     │   Shared Runtime
  │   Tool Registry · Executor    │
  └──────────┬───────────────────┘
             │
  ┌──────────▼───────────────────┐
  │   OpenAI-Compatible Client    │   Any LLM Provider
  └──────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python >= 3.10
- Node.js >= 18 (with pnpm)

### Install & Run

**Option 1 — One-click (Windows)**
```powershell
.\start.bat
```
Choose `2` to install dependencies and launch both servers.

**Option 2 — PowerShell script**
```powershell
conda activate base
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -StartBackend -StartFrontend
```

**Option 3 — Manual**
```powershell
# Backend
pip install -r requirements.txt
python -m uvicorn fastapi_app.main:app --port 3001

# Frontend
cd frontend && pnpm install && pnpm dev
```

### Configure

```powershell
copy .env.example .env
```

```env
SC_AGENT_API_KEY=your-api-key
SC_AGENT_BASE_URL=https://api.openai.com/v1
SC_AGENT_MODEL=gpt-4o
```

Works with any OpenAI-compatible endpoint — DeepSeek, Qwen, local Ollama, etc. Without `.env`, the backend runs in **Demo Mode** with mock replies.

Open **http://localhost:8888** and start coding.

<!-- TODO: 添加启动后的着陆页截图
     建议文件名: docs/images/landing.png -->

## SDK

Use the agent engine programmatically:

```python
from agent import AgentLLMConfig, OpenAICompatibleClient
from coding_agent import build_coding_agent
from fastapi_app.runtime.zonix_runner import ZonixChatSession

config = AgentLLMConfig.from_env(".env")
client = OpenAICompatibleClient(config)

agent = build_coding_agent(
    client,
    workspace="path/to/project",
)

session = ZonixChatSession(agent=agent)
response = session.ask("Refactor the auth module")
print(response.final_output)
```

<!-- TODO: 添加代码编辑器 + AI对话的协作截图
     建议文件名: docs/images/collaboration.png -->

## @Skill System

Create markdown skill files to inject domain knowledge:

```markdown
---
name: api-guidelines
description: REST API coding conventions for this project
---
# API Guidelines
- Use snake_case for endpoints
- Always validate with Pydantic v2
...
```

Place at `.agents/skills/<name>/SKILL.md` (local) or `builtin_skills/<name>/SKILL.md` (global).

Type `@` in the chat to pick a skill, or let the agent auto-discover relevant ones.

Built-in skills include: `code-review`, `frontend-design`, `security-audit`, `systematic-debugging`, `test-driven-development`, and more.

## Tool Reference

| Tool | Description |
|---|---|
| `list_file` | List directory contents with depth control |
| `glob_file` | Glob pattern file search |
| `read_file` | Read file content with pagination |
| `grep_file` | Regex search across files |
| `write_file` | Create or overwrite a file |
| `replace_file` | Safe chunk-based file editing |
| `run_command` | Run a short shell command with a hard timeout |
| `start_task` | Start a long-running or interactive command |
| `task_input` | Send input to a running task |
| `task_wait` | Wait for more task output |
| `task_stop` | Stop a running task |

Read-only tools run **in parallel** when possible — no waiting for sequential file reads.

## Project Structure

```
SuperCode/
├── agent/              # Provider client, model adapter, and UI event/state records
├── zonix/              # Shared agent, workflow, team, tool, and execution runtime
├── coding_agent/       # Coding agent — file ops, shell, git tools
├── plan_agent/         # Planning agent — task decomposition, checklists
├── deploy_agent/       # Deploy agent — SSH, testing, packaging
├── fastapi_app/        # Backend server (SSE, terminal PTY, session store)
├── frontend/           # React dashboard (Vite, Tailwind v4, Monaco)
├── builtin_skills/     # Pre-packaged markdown skills
├── examples/          # CLI entrypoint and demo workspace
├── scripts/            # Bootstrap and build scripts
└── start.bat           # One-click Windows launcher
```

---

## 核心特性

**三种专属智能体** — 规划、编码、部署 — 通过统一运行时编排。每个智能体是可插拔的提示模型，拥有独立工具集，共享执行引擎。

| | |
|---|---|
| 多智能体架构 | 解耦引擎，`CodingAgent`、`PlanAgent`、`DeployAgent` 各自专精 |
| 实时思考流 | SSE 驱动，可视化链式推理、工具调用、终端输出 |
| 只读工具并行 | 搜索、读取等只读工具线程池并行执行，响应更快 |
| @技能系统 | 输入 `@` 注入项目级 Markdown 规则，或由 AI 自动激活 |
| Monaco 编辑器 | 代码编辑 + 文件树 + Diff 视图 + Git 集成 |
| 真实终端 | xterm.js + PTY 后端，支持交互等待与确认安全机制 |
| 看板管理 | 内置拖拽看板，富文本任务描述 |
| 计划构建器 | 编码前交互式问答规划，富文本计划编辑器 |
| OpenAI 兼容 | 支持任何 OpenAI 格式 API — GPT、DeepSeek、Qwen、本地模型 |

<!-- TODO: 同上需要的功能截图 -->

## 快速启动

### 环境要求

- Python >= 3.10
- Node.js >= 18（需安装 pnpm）

### 启动

**方式一 — 一键启动（Windows）**
```powershell
.\start.bat
```
选择 `2` 自动安装依赖并启动前后端。

**方式二 — PowerShell 脚本**
```powershell
conda activate base
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -StartBackend -StartFrontend
```

**方式三 — 手动启动**
```powershell
# 后端
pip install -r requirements.txt
python -m uvicorn fastapi_app.main:app --port 3001

# 前端
cd frontend && pnpm install && pnpm dev
```

### 配置

```powershell
copy .env.example .env
```

```env
SC_AGENT_API_KEY=你的密钥
SC_AGENT_BASE_URL=https://api.openai.com/v1
SC_AGENT_MODEL=gpt-4o
```

兼容任何 OpenAI 格式接口 — DeepSeek、Qwen、本地 Ollama 等。未配置 `.env` 时，后端以 **Demo 模式** 运行模拟回复。

打开 **http://localhost:8888** 开始使用。

---

<div align="center">

**[MIT License](LICENSE)** — Built with ❤️ by the open-source community

Issues and PRs welcome → [GitHub Issues](https://github.com/zongxi1115/SuperCode/issues)

</div>
