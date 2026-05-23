# SuperCode

## agent / coding_agent

仓库里已经放入两层结构：

```text
agent/
coding_agent/
examples/
```

- `agent/`：通用智能体框架，只保留抽象接口和执行循环
- `coding_agent/`：编码场景专用 brain、提示词和工具实现

特点：

1. 调用入口简单，支持单轮 `agent.run("任务")`
2. 也支持多轮 `session.ask("问题")`
3. 用户可以连续追问，自动保留上下文
4. `agent` 不绑定具体工具实现，工具可被场景包替换
5. `coding_agent` 使用独立提示词和编码专用工具
6. 运行时可以实时看到思考、工具调用和工具结果
7. 不依赖复杂链式 API
8. 注释和文档采用中文
9. 自带一个可接真实 API 的多轮对话 demo

### 运行 demo

先编辑 `.env`，填入你自己的真实接口配置。

再在仓库根目录执行：

```powershell
conda activate base
python examples/run_demo.py
```

运行后你可以直接连续提问，比如：

- `帮我看看这个 demo_workspace 是干嘛的`
- `那 main.py 和 helper.py 的关系是什么`
- `顺手给我总结成 3 点`

### 多轮调用示例

```python
from agent import (
    AgentLLMConfig,
    ChatSession,
    CodingAgent,
    OpenAICompatibleClient,
)
from coding_agent import CodingPromptBrain, build_coding_tools

config = AgentLLMConfig.from_env(".env")
client = OpenAICompatibleClient(config)

agent = CodingAgent(
    brain=CodingPromptBrain(client),
    tools=build_coding_tools(),
    workspace="examples/demo_workspace",
)

session = ChatSession(agent=agent)

answer_1 = session.ask("帮我看看这个项目目录")
print(answer_1.final_output)

answer_2 = session.ask("继续说一下 src/main.py 是做什么的")
print(answer_2.final_output)
```

### 实时显示中间过程

如果你希望在运行时看到中间过程，可以给 `ask()` 或 `run()` 传一个事件回调：

```python
from agent import AgentEvent

def on_event(event: AgentEvent) -> None:
    print(event.type, event.message)

response = session.ask("先看看项目结构", on_event=on_event)
```

### coding_agent 工具接口

`coding_agent` 当前提供这些工具名：

- `list_file(path, include_ignored?, max_depth?, limit?)`
- `glob_file(pattern, search_path, include_ignored?, limit?)`
- `read_file(filename, offset?, limit?, start_line?, end_line?)`
- `grep_file(regex, search_path, output_mode?, glob?, file_type?, include_ignored?, limit?)`
- `write_file(filename, content)`
- `replace_file(filename, old_content, new_content)`
- `excecute(content, timeout)`
- `terminal_input(content, timeout)`
- `terminal_wait(timeout)`

说明：

- `list_file(..., include_ignored?)`、`glob_file(..., include_ignored?)` 和 `grep_file(..., include_ignored?)` 默认都会跳过 `node_modules`、`.git`、`dist`、`build`、`__pycache__` 等生成目录。
- 只有在你明确想查看或搜索这些目录时，才需要传 `include_ignored=true`。
- `list_file(...)` 默认只做浅层目录浏览；推荐先 `glob_file(...)` 找文件，再 `grep_file(...)` 看内容分布，最后 `read_file(...)` 精读。
- `glob_file(...)` 最多返回 100 个结果；如果被截断，应该继续缩小 pattern 或 search_path。
- `grep_file(...)` 支持三种输出模式：
  - `content`：返回命中的文件、行号和文本
  - `files_with_matches`：只返回命中文件
  - `count`：返回每个文件的命中次数和总数
- `grep_file(...)` 可通过 `glob` 或 `file_type` 限制搜索范围。
- `read_file(...)` 默认从文件开头读取；返回里会带 `total_lines`、`total_chars` 等元信息；如果返回过长，会在最大输出长度处截断，并明确提示还有内容未读完，继续用更小的 `offset/limit` 或 `start_line/end_line` 分段读取。
- `execute(...)`、`terminal_input(...)`、`terminal_wait(...)` 的 `timeout` 都是必填秒数。
- 交互式终端结果会带 `status`、`exit_reason`、`awaiting_input`、`input_prompt`、`input_request` 等字段：
  - `status=completed`：命令已结束，立即返回最终结果
  - `status=running` 且 `exit_reason=awaiting_input`：命令正在等输入，应调用 `terminal_input(...)`
  - `status=running` 且 `exit_reason=idle`：本次已经收集到一段输出，但命令暂时安静下来了
  - `status=running` 且 `exit_reason=timeout`：在这次等待窗口内没有等到完成，只返回该窗口期间收集到的新增输出
- `terminal_wait(...)` 如果遇到命令已在下一次等待前完成，会返回缓存的最终结果，而不是因为终端已释放直接报错。

### 配置项说明

- `SC_AGENT_API_KEY`：模型服务的密钥
- `SC_AGENT_BASE_URL`：OpenAI 兼容接口基础地址，例如 `https://api.openai.com/v1`
- `SC_AGENT_MODEL`：模型名称
- `SC_AGENT_TIMEOUT`：接口超时时间，单位秒
- `SC_AGENT_INCLUDE_THOUGHTS_IN_CONTEXT`：是否把思考内容写入后续模型上下文，默认 `false`；前端仍会实时展示思考过程

## 部署运行方案

项目由两部分组成：**FastAPI 后端** 和 **React 前端**，需分别启动。

### 1. 环境准备

```powershell
# Python 环境（推荐 conda）
conda activate base
# 确保Python >= 3.10

# Node 环境（前端需要）
# 确保已安装 Node >= 18 和 pnpm
```

### 2. 配置 API 密钥

```powershell
# 复制环境变量模板
copy .env.example .env
# 编辑 .env，填入你的真实模型服务配置：
#   SC_AGENT_API_KEY   = 你的 API Key
#   SC_AGENT_BASE_URL  = OpenAI 兼容接口地址（如 https://api.openai.com/v1）
#   SC_AGENT_MODEL     = 模型名称
```

> 如果不配置 `.env`，后端仍可启动，但会进入 **demo 模式**（模拟回复，不调用真实模型），方便前端联调。

### 2.5 快速准备脚本

如果你的机器已经有基础环境（`Python 3.10+`、`Node 18+`、`pnpm`），可以直接在仓库根目录执行：

```powershell
conda activate base
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1
```

这个脚本会帮你：

- 检查 Python / Node / pnpm 是否可用
- 自动把 `.env.example` 复制成 `.env`（如果你还没有 `.env`）
- 安装后端依赖 `fastapi_app/requirements.txt`
- 安装前端依赖 `frontend/package.json`
- 输出后端、前端和 CLI demo 的启动命令

常用参数：

```powershell
# 只安装依赖
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -InstallOnly

# 只准备后端
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -BackendOnly

# 只准备前端
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -FrontendOnly

# 安装完成后自动拉起后端和前端
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -StartBackend -StartFrontend

# 如果缺少 Python / Node / pnpm，尝试自动安装基础工具后再继续
powershell -ExecutionPolicy Bypass -File .\scripts\quick-start.ps1 -AutoInstallTools
```

说明：

- `-AutoInstallTools` 会在缺少基础工具时尝试自动补齐
- `Python` 和 `Node` 优先通过 `winget` 安装
- `pnpm` 会优先尝试 `npm install -g pnpm`，不行再退回 `winget`
- 如果 `winget` 刚装完工具但当前终端还没刷新 PATH，重新打开终端再跑一次脚本即可

如果你不想记参数，也可以直接双击仓库根目录的 [start.bat](D:/vibe_projs/SuperCode/start.bat)。
它会弹出交互菜单，让你选择：

- 只安装依赖
- 安装后直接启动前后端
- 只准备前端或后端
- 先自动补基础工具，再安装或启动

### 3. 启动后端

```powershell
# 安装 Python 依赖
pip install -r fastapi_app/requirements.txt

# 启动 FastAPI 服务（默认 8000 端口）
python -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 启动前端

```powershell
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器（默认 5173 端口，已代理 /api 到后端）
pnpm dev
```

浏览器打开 `http://localhost:5173` 即可使用。

### Skills 功能

项目现在支持在聊天框里通过 `@` 提及 skills。

- 工作区 skills：放在 `.agents/skills/<skill-name>/SKILL.md`
- 内置 skills：放在仓库根目录 `builtin_skills/<skill-name>/SKILL.md`
- `SKILL.md` 建议使用 YAML frontmatter，至少包含：

```md
---
name: my-skill
description: 这份 skill 是做什么的
---
```

- 前端会把 skill 作为 `@` mention 候选项展示
- 后端会把 `@skill` 解析为“本轮激活技能”，并把 skill 内容注入当前轮的 agent 上下文
- 即使用户不显式 `@`，后端也会先加载所有 skill 的 `name + description` 作为技能目录，让 AI 自主发现可用 skill；命中描述的 skill 会被自动激活
- 当前实现使用序列化 token `@[skill:<id>]` 保存 mention

### 5. 纯 Agent CLI 模式（无需前后端）

如果你只想用命令行对话，不启动 Web UI：

```powershell
conda activate base
python examples/run_demo.py
```

### 项目结构一览

```text
SuperCode/
├── agent/              # 通用智能体框架（抽象接口 + 执行循环）
├── coding_agent/       # 编码场景专用 brain、提示词和工具实现
├── fastapi_app/        # FastAPI 后端（SSE 流式推送 + 终端 + 文件树）
├── frontend/           # React + Vite + Tailwind 前端
├── examples/           # CLI demo 入口
├── .env.example        # 环境变量模板
└── README.md
```
