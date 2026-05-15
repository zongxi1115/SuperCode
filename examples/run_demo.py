from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import (
    AgentEvent,
    AgentLLMConfig,
    ChatSession,
    CodingAgent,
    OpenAICompatibleClient,
)
from coding_agent import CodingPromptBrain, build_coding_tools


def render_live_event(event: AgentEvent) -> None:
    """把智能体中间过程实时打印到终端。"""

    prefix = f"[步骤 {event.step_index}] " if event.step_index is not None else ""

    if event.type == "turn_started":
        print("系统> 正在处理这轮请求...")
        return

    if event.type == "thought":
        print(f"{prefix}思考> {event.thought}")
        return

    if event.type == "tool_call" and event.tool_call is not None:
        print(f"{prefix}工具调用> {event.tool_call.name} {event.tool_call.arguments}")
        return

    if event.type == "tool_result" and event.tool_result is not None:
        status = "成功" if event.tool_result.success else "失败"
        print(f"{prefix}工具结果> {event.tool_result.name} {status}")
        if event.tool_result.success:
            print(f"{prefix}结果预览> {_preview_text(event.tool_result.output)}")
        else:
            print(f"{prefix}错误信息> {event.tool_result.error_message}")
        return

    if event.type == "final" and event.final_answer is not None:
        print(f"{prefix}收尾> 已生成最终答复。")
        return

    if event.type == "limit_reached":
        print(f"{prefix}系统> 已达到最大步数限制。")
        return


def _preview_text(value: object, limit: int = 280) -> str:
    """压缩长输出，方便终端实时展示。"""

    text = str(value).strip().replace("\r\n", "\n").replace("\n", " | ")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> None:
    """运行真实 API 多轮对话 demo。"""

    workspace = Path(__file__).resolve().parent / "demo_workspace"

    try:
        config = AgentLLMConfig.from_env(PROJECT_ROOT / ".env")
    except ValueError as exc:
        print(f"配置错误：{exc}")
        print("请检查项目根目录下的 .env，并填入真实接口配置。")
        return

    client = OpenAICompatibleClient(config)
    agent = CodingAgent(
        brain=CodingPromptBrain(client),
        tools=build_coding_tools(),
        workspace=workspace,
        max_steps=config.max_steps,
    )
    session = ChatSession(
        agent=agent,
        task=(
            "你是一个可以多轮对话的编码智能体。"
            "用户可以自由提问、继续追问。"
            "如果需要了解项目，请结合工具查看当前工作区。"
            "回答尽量清楚直接。"
        ),
    )

    print("=== 多轮对话 Demo ===")
    print("输入你的问题后按回车即可连续对话。")
    print("特殊命令：/history 查看上下文，/steps 查看上一轮轨迹，/clear 清空上下文，/exit 退出。")
    print("每轮执行时会实时显示思考、工具调用和工具结果。")
    print()

    last_response = None
    while True:
        try:
            user_input = input("你> ").strip()
        except EOFError:
            print("\n检测到输入结束，会话已退出。")
            break
        except KeyboardInterrupt:
            print("\n检测到手动中断，会话已退出。")
            break

        if not user_input:
            continue

        if user_input == "/exit":
            print("会话已结束。")
            break

        if user_input == "/history":
            print("=== 当前上下文 ===")
            print(session.history_as_text())
            print()
            continue

        if user_input == "/steps":
            if last_response is None:
                print("还没有可查看的执行轨迹。")
                print()
                continue

            print("=== 上一轮执行轨迹 ===")
            for step in last_response.steps:
                print(f"[步骤 {step.index}] 思考: {step.thought}")
                if step.tool_call:
                    print(f"  工具: {step.tool_call.name} {step.tool_call.arguments}")
                if step.tool_result:
                    print(f"  成功: {step.tool_result.success}")
                    if step.tool_result.success:
                        print(f"  输出: {step.tool_result.output}")
                    else:
                        print(f"  错误: {step.tool_result.error_message}")
                if step.final_answer:
                    print(f"  最终答复: {step.final_answer}")
                print()
            continue

        if user_input == "/clear":
            session.clear()
            last_response = None
            print("上下文已清空。")
            print()
            continue

        response = session.ask(user_input, on_event=render_live_event)
        last_response = response
        print(f"助手> {response.final_output}")
        print()


if __name__ == "__main__":
    main()
