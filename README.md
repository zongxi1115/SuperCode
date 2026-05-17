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

- `list_file(path, include_ignored?)`
- `read_file(filename, start_line, end_line)`
- `grep_file(regex, search_path, include_ignored?)`
- `write_file(filename, content)`
- `replace_file(filename, old_content, new_content)`
- `excecute(content, timeout)`
- `terminal_input(content, timeout)`
- `terminal_wait(timeout)`

说明：

- `list_file(..., include_ignored?)` 和 `grep_file(..., include_ignored?)` 默认都会跳过 `node_modules`、`.git`、`dist`、`build`、`__pycache__` 等生成目录。
- 只有在你明确想查看或搜索这些目录时，才需要传 `include_ignored=true`。

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
