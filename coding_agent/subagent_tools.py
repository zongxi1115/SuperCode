from __future__ import annotations

import re
import uuid
from typing import Any

from agent.llm_client import OpenAICompatibleClient
from agent.schema import AgentEvent, AgentResponse, AgentState, StepRecord, ToolCall, ToolResult
from fastapi_app.runtime.zonix_runner import ZonixAgentRunner
from zonix import Agent
from zonix.tools import ToolContext, ToolDefinition

from .tool_common import (
    SUBAGENT_SUMMARY_MAX_CHARS,
    _compact_text,
    _truncate_text,
)


def _build_code_exploration_tools() -> list[ToolDefinition]:
    from coding_agent.registry import build_code_exploration_tools

    return build_code_exploration_tools()


class CodeExplorationDelegator:
    """委派只读代码探索子智能体。"""

    def delegate(
        self,
        context: ToolContext,
        *,
        task: str,
        focus_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        task = task.strip()
        if not task:
            raise ValueError("task 不能为空。")
        normalized_focus_paths = self._normalize_focus_paths(focus_paths)
        subagent_id = f"code-exploration-{uuid.uuid4().hex[:10]}"
        subagent_meta = self._build_subagent_meta(
            context,
            subagent_id=subagent_id,
            task=task,
        )

        snapshot = self._build_snapshot(
            subagent_id=subagent_id,
            task=task,
            focus_paths=normalized_focus_paths,
            status="running",
            steps=[],
        )
        snapshot = self._with_parent_metadata(snapshot, subagent_meta)
        self._emit_snapshot(context, snapshot)
        self._emit_subagent_event(context, subagent_meta, "assistant_started")

        try:
            subagent = self._build_subagent(context)
            response = self._run_subagent(
                context,
                subagent,
                task=self._build_subagent_task(task, normalized_focus_paths),
                meta=subagent_meta,
            )
        except Exception as exc:  # noqa: BLE001 - 工具输出要把失败状态给 UI 展示
            self._emit_subagent_event(
                context,
                subagent_meta,
                "error",
                {"message": str(exc)},
            )
            self._emit_subagent_event(
                context,
                subagent_meta,
                "assistant_done",
                {"final_output": "", "status": "error", "error": str(exc)},
            )
            snapshot = {
                **snapshot,
                "status": "error",
                "finalOutput": "",
                "error": str(exc),
            }
            self._emit_snapshot(context, snapshot)
            return {
                "status": "error",
                "task": task,
                "focus_paths": normalized_focus_paths,
                "error": str(exc),
                "data_part": {"type": "data-subagent-task", "data": snapshot},
            }

        final_snapshot = self._snapshot_from_response(
            response=response,
            subagent_id=subagent_id,
            task=task,
            focus_paths=normalized_focus_paths,
        )
        final_snapshot = self._with_parent_metadata(final_snapshot, subagent_meta)
        self._emit_subagent_event(
            context,
            subagent_meta,
            "assistant_done",
            {"final_output": final_snapshot["finalOutput"], "status": final_snapshot["status"]},
        )
        self._emit_snapshot(context, final_snapshot)
        return {
            "status": final_snapshot["status"],
            "task": task,
            "focus_paths": normalized_focus_paths,
            "files_read": final_snapshot["filesRead"],
            "commands_run": final_snapshot["commandsRun"],
            "findings": final_snapshot["findings"],
            "recommended_files": final_snapshot["recommendedFiles"],
            "final_output": final_snapshot["finalOutput"],
            "data_part": {"type": "data-subagent-task", "data": final_snapshot},
        }

    def _build_subagent_meta(
        self,
        context: ToolContext,
        *,
        subagent_id: str,
        task: str,
    ) -> dict[str, Any]:
        current_call = getattr(context, "call", None)
        parent_tool_call_id = str(
            getattr(current_call, "call_id", None)
            or context.metadata.get("current_tool_call_id")
            or ""
        ).strip()
        parent_assistant_id = str(context.metadata.get("runtime_assistant_id") or "").strip()
        return {
            "subagent_id": subagent_id,
            "message_id": f"subagent-message-{subagent_id}",
            "title": "代码探索",
            "agent_type": "code_exploration",
            "task": task,
            "parent_tool_call_id": parent_tool_call_id or None,
            "parent_assistant_id": parent_assistant_id or None,
        }

    def _with_parent_metadata(
        self,
        snapshot: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **snapshot,
            "parentToolCallId": meta.get("parent_tool_call_id"),
            "parentAssistantId": meta.get("parent_assistant_id"),
        }

    def _normalize_focus_paths(self, raw_value: object) -> list[str]:
        if raw_value is None:
            return []
        if not isinstance(raw_value, list):
            raise ValueError("focus_paths 必须是字符串数组。")
        paths: list[str] = []
        seen: set[str] = set()
        for raw_path in raw_value:
            path = str(raw_path or "").strip().replace("\\", "/")
            if not path or path in seen:
                continue
            paths.append(path)
            seen.add(path)
            if len(paths) >= 12:
                break
        return paths

    def _build_subagent(self, context: ToolContext) -> Agent:
        factory = context.metadata.get("code_exploration_subagent_factory")
        if callable(factory):
            return factory(context)

        client = context.metadata.get("llm_client")
        if not isinstance(client, OpenAICompatibleClient):
            raise RuntimeError("缺少 llm_client，无法启动代码探索子智能体。")

        from coding_agent.agent import build_code_exploration_agent

        return build_code_exploration_agent(
            client,
            workspace=context.workspace,
            metadata={
                "include_thoughts_in_context": bool(
                    context.metadata.get("include_thoughts_in_context")
                ),
                "project_root": context.metadata.get("project_root"),
                "cancel_event": context.metadata.get("cancel_event"),
            },
        )

    def _build_subagent_task(self, task: str, focus_paths: list[str]) -> str:
        lines = [
            "请作为只读代码探索子智能体完成以下侦察任务。",
            "",
            f"任务：{task}",
        ]
        if focus_paths:
            lines.extend(
                [
                    "",
                    "优先关注路径：",
                    *[f"- {path}" for path in focus_paths],
                ]
            )
        lines.extend(
            [
                "",
                "请只返回摘要、关键路径、调用链/数据流、发现和建议下一步。",
            ]
        )
        return "\n".join(lines)

    def _run_subagent(
        self,
        context: ToolContext,
        subagent: Agent,
        *,
        task: str,
        meta: dict[str, Any],
    ) -> AgentResponse:
        state = AgentState(
            task="你是一个只读代码探索子智能体，请围绕主智能体委派的任务收集代码事实。",
            current_input=task,
            conversation_messages=[],
        )

        def on_event(event: AgentEvent) -> None:
            self._emit_agent_event(context, meta, event)

        return ZonixAgentRunner(subagent).run_turn(state, on_event=on_event)

    def _snapshot_from_response(
        self,
        *,
        response: AgentResponse,
        subagent_id: str,
        task: str,
        focus_paths: list[str],
    ) -> dict[str, Any]:
        files_read = self._collect_files_read(response.steps)
        commands_run = self._collect_commands_run(response.steps)
        tool_names = self._collect_tool_names(response.steps)
        final_output = _truncate_text(
            response.final_output.strip(), SUBAGENT_SUMMARY_MAX_CHARS
        )
        findings = self._extract_findings(final_output)
        recommended_files = self._extract_recommended_files(final_output, files_read)
        steps = self._snapshot_steps(response.steps)
        current_thought = next(
            (step.thought for step in reversed(response.steps) if step.thought.strip()),
            "",
        )
        return self._build_snapshot(
            subagent_id=subagent_id,
            task=task,
            focus_paths=focus_paths,
            status="completed",
            steps=steps,
            current_thought=current_thought,
            files_read=files_read,
            commands_run=commands_run,
            findings=findings,
            recommended_files=recommended_files,
            tool_names=tool_names,
            final_output=final_output,
        )

    def _build_snapshot(
        self,
        *,
        subagent_id: str,
        task: str,
        focus_paths: list[str],
        status: str,
        steps: list[dict[str, Any]],
        current_thought: str = "",
        files_read: list[str] | None = None,
        commands_run: list[str] | None = None,
        findings: list[str] | None = None,
        recommended_files: list[str] | None = None,
        tool_names: list[str] | None = None,
        final_output: str = "",
    ) -> dict[str, Any]:
        message_id = f"subagent-message-{subagent_id}"
        return {
            "id": subagent_id,
            "messageId": message_id,
            "kind": "code_exploration",
            "title": "代码探索",
            "agentType": "code_exploration",
            "status": status,
            "task": task,
            "focusPaths": focus_paths,
            "currentThought": _compact_text(current_thought, 500),
            "steps": steps,
            "stepCount": len(steps),
            "filesRead": files_read or [],
            "changedFiles": [],
            "commandsRun": commands_run or [],
            "findings": findings or [],
            "recommendedFiles": recommended_files or [],
            "toolNames": tool_names or [],
            "finalOutput": final_output,
        }

    def _snapshot_steps(self, steps: list[StepRecord]) -> list[dict[str, Any]]:
        snapshot_steps: list[dict[str, Any]] = []
        for step in steps:
            tool_calls = self._step_tool_calls(step)
            name = (
                ", ".join(tool.name for tool in tool_calls) if tool_calls else "final"
            )
            has_error = any(
                result is not None and not result.success
                for result in self._step_tool_results(step)
            )
            snapshot_steps.append(
                {
                    "id": f"step-{step.index}",
                    "name": name,
                    "status": "error" if has_error else "completed",
                    "thought": _compact_text(step.thought, 300),
                }
            )
        return snapshot_steps

    def _collect_files_read(self, steps: list[StepRecord]) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name != "read_file":
                    continue
                filename = str(tool_call.arguments.get("filename") or "").strip()
                if filename and filename not in seen:
                    files.append(filename)
                    seen.add(filename)
        return files

    def _collect_commands_run(self, steps: list[StepRecord]) -> list[str]:
        commands: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name not in {"run_command", "start_task"}:
                    continue
                command = str(
                    tool_call.arguments.get("content")
                    or tool_call.arguments.get("command")
                    or ""
                ).strip()
                if command and command not in seen:
                    commands.append(command)
                    seen.add(command)
        return commands

    def _collect_tool_names(self, steps: list[StepRecord]) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for step in steps:
            for tool_call in self._step_tool_calls(step):
                if tool_call.name not in seen:
                    names.append(tool_call.name)
                    seen.add(tool_call.name)
        return names

    def _extract_findings(self, final_output: str) -> list[str]:
        findings: list[str] = []
        for raw_line in final_output.splitlines():
            line = raw_line.strip().lstrip("-*0123456789.、) ")
            if not line or line.startswith("#"):
                continue
            findings.append(_compact_text(line, 220))
            if len(findings) >= 6:
                break
        return findings

    def _extract_recommended_files(
        self,
        final_output: str,
        files_read: list[str],
    ) -> list[str]:
        recommended: list[str] = []
        seen: set[str] = set()
        path_pattern = re.compile(r"[\w@./\\-]+\.[A-Za-z0-9]{1,8}")
        for candidate in [*path_pattern.findall(final_output), *files_read]:
            normalized = candidate.strip("`'\".,:;()[]{}").replace("\\", "/")
            if not normalized or normalized in seen:
                continue
            recommended.append(normalized)
            seen.add(normalized)
            if len(recommended) >= 8:
                break
        return recommended

    def _step_tool_calls(self, step: StepRecord) -> list[ToolCall]:
        if step.tool_calls:
            return step.tool_calls
        return [step.tool_call] if step.tool_call is not None else []

    def _step_tool_results(self, step: StepRecord) -> list[Any]:
        if step.tool_results:
            return step.tool_results
        return [step.tool_result] if step.tool_result is not None else []

    def _emit_snapshot(self, context: ToolContext, snapshot: dict[str, Any]) -> None:
        emitter = context.metadata.get("runtime_event_emitter")
        if not callable(emitter):
            return
        try:
            emitter("data-subagent-task", {"data": snapshot})
        except TypeError:
            emitter("data-subagent-task", snapshot)

    def _emit_agent_event(
        self,
        context: ToolContext,
        meta: dict[str, Any],
        event: AgentEvent,
    ) -> None:
        payload: dict[str, Any] = {
            "event": event.type,
            "step_index": event.step_index,
            "message": event.message,
        }
        if event.delta is not None:
            payload["delta"] = event.delta
        if event.thought is not None:
            payload["thought"] = event.thought
        if event.final_answer is not None:
            payload["final_answer"] = event.final_answer
        if event.usage is not None:
            payload["usage"] = event.usage
        if event.tool_call is not None:
            payload["tool_call"] = self._tool_call_payload(event.tool_call)
        if event.tool_result is not None:
            payload["tool_result"] = self._tool_result_payload(event.tool_result)
        self._emit_subagent_event(context, meta, event.type, payload)

    def _emit_subagent_event(
        self,
        context: ToolContext,
        meta: dict[str, Any],
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        emitter = context.metadata.get("runtime_event_emitter")
        if not callable(emitter):
            return
        event_payload = {
            **meta,
            **(payload or {}),
            "event": event,
        }
        try:
            emitter("subagent_event", event_payload)
        except TypeError:
            emitter("data-subagent-event", {"data": event_payload})

    def _tool_call_payload(self, tool_call: ToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        }

    def _tool_result_payload(self, tool_result: ToolResult) -> dict[str, Any]:
        return {
            "name": tool_result.name,
            "tool_call_id": tool_result.tool_call_id,
            "output": tool_result.output,
            "success": tool_result.success,
            "error_message": tool_result.error_message,
        }


_CODE_EXPLORATION_DELEGATOR = CodeExplorationDelegator()


def delegate_code_exploration(
    ctx: ToolContext,
    task: str,
    focus_paths: list[str] | None = None,
) -> dict[str, Any]:
    """委派只读代码探索子智能体查找相关模块、调用链、数据流和测试入口。"""

    return _CODE_EXPLORATION_DELEGATOR.delegate(
        ctx,
        task=task,
        focus_paths=focus_paths,
    )


delegate_code_exploration.supports_parallel = True

