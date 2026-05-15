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
    max_steps=config.max_steps,
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

- `list_file(path)`
- `read_file(filename, start_line, end_line)`
- `grep_file(regex, context_line, search_path)`
- `write_file(filename, content)`
- `replace_file(filename, old_content, new_content)`
- `excecute(content)`

### 配置项说明

- `SC_AGENT_API_KEY`：模型服务的密钥
- `SC_AGENT_BASE_URL`：OpenAI 兼容接口基础地址，例如 `https://api.openai.com/v1`
- `SC_AGENT_MODEL`：模型名称
- `SC_AGENT_TIMEOUT`：接口超时时间，单位秒
- `SC_AGENT_MAX_STEPS`：智能体最大执行步数
