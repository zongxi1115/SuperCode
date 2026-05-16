from __future__ import annotations

import re
from typing import Any


def sse_data(payload: dict[str, Any] | str) -> str:
    """Serialize one Server-Sent Events data frame."""

    import json

    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class UIMessageStreamAdapter:
    """Convert SuperCode's internal stream events to AI SDK UI message parts."""

    def __init__(self) -> None:
        self.message_id: str | None = None
        self.step_started = False
        self.text_id: str | None = None
        self.text_open = False
        self.text_index = 0
        self.reasoning_id: str | None = None
        self.reasoning_open = False
        self.reasoning_index = 0
        self.reasoning_text = ""
        self.tool_names_by_id: dict[str, str] = {}
        self.streaming_tool_input_ids: set[str] = set()

    def convert(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = str(event.get("type", ""))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if event_type == "user_message":
            return []

        if event_type == "assistant_started":
            message_id = str(payload.get("id") or "").strip() or "assistant-message"
            self.message_id = message_id
            self.step_started = True
            return [
                {"type": "start", "messageId": message_id},
                {"type": "start-step"},
            ]

        if event_type == "assistant_reset":
            parts = self._close_text()
            parts.append({"type": "data-assistant-reset", "data": payload})
            return parts

        if event_type == "assistant_delta":
            delta = str(payload.get("delta") or "")
            if not delta:
                return []
            return [
                *self._ensure_started(str(payload.get("id") or "")),
                *self._ensure_text_started(),
                {"type": "text-delta", "id": self.text_id, "delta": delta},
            ]

        if event_type == "assistant_done":
            return [
                *self._close_reasoning(),
                *self._close_text(),
                *self._finish_step(),
                {"type": "finish"},
            ]

        if event_type == "thought_delta":
            delta = str(payload.get("delta") or "")
            if not delta:
                return []
            parts = [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                *self._ensure_reasoning_started(),
            ]
            self.reasoning_text += delta
            parts.append({"type": "reasoning-delta", "id": self.reasoning_id, "delta": delta})
            return parts

        if event_type == "thought":
            thought = str(payload.get("thought") or "")
            if not thought.strip():
                return []

            if thought.startswith(self.reasoning_text):
                delta = thought[len(self.reasoning_text) :]
            else:
                delta = thought
            self.reasoning_text = thought

            parts = [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                *self._ensure_reasoning_started(),
            ]
            if delta:
                parts.append({"type": "reasoning-delta", "id": self.reasoning_id, "delta": delta})
            parts.extend(self._close_reasoning())
            return parts

        if event_type == "tool_call":
            tool_call_id = str(payload.get("id") or "").strip()
            tool_name = str(payload.get("name") or "").strip()
            if not tool_call_id or not tool_name:
                return []
            self.tool_names_by_id[tool_call_id] = tool_name
            if tool_call_id in self.streaming_tool_input_ids:
                tool_input_parts = [
                    {
                        "type": "tool-input-available",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "input": payload.get("arguments") or {},
                        "providerExecuted": False,
                        "dynamic": True,
                    }
                ]
            else:
                tool_input_parts = self._tool_input_parts(
                    tool_call_id,
                    tool_name,
                    payload.get("arguments") or {},
                    replay_as_deltas=False,
                )
            return [
                *self._close_reasoning(),
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                *tool_input_parts,
                {"type": "data-tool-call", "data": payload},
            ]

        if event_type == "tool_input_started":
            tool_call_id = str(payload.get("id") or "").strip()
            tool_name = str(payload.get("name") or "").strip()
            if not tool_call_id or not tool_name:
                return []
            self.tool_names_by_id[tool_call_id] = tool_name
            self.streaming_tool_input_ids.add(tool_call_id)
            return [
                *self._close_reasoning(),
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                {
                    "type": "tool-input-start",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                },
            ]

        if event_type == "tool_input_delta":
            tool_call_id = str(payload.get("id") or "").strip()
            if not tool_call_id:
                return []
            self.streaming_tool_input_ids.add(tool_call_id)
            return [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                {
                    "type": "tool-input-delta",
                    "toolCallId": tool_call_id,
                    "inputTextDelta": str(payload.get("delta") or ""),
                },
            ]

        if event_type == "tool_result":
            tool_call_id = str(payload.get("id") or "").strip()
            if not tool_call_id:
                return []
            tool_name = str(payload.get("name") or self.tool_names_by_id.get(tool_call_id) or "").strip()
            self.tool_names_by_id[tool_call_id] = tool_name

            output = payload.get("output")
            parts: list[dict[str, Any]] = [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                {
                    "type": "tool-output-available",
                    "toolCallId": tool_call_id,
                    "output": output,
                    "dynamic": True,
                },
                {"type": "data-tool-result", "data": payload},
            ]
            if isinstance(payload.get("terminal_output"), str):
                parts.append({"type": "data-terminal-output", "data": {"output": payload["terminal_output"]}})
            if isinstance(payload.get("preview_url"), str):
                parts.append({"type": "data-preview-url", "data": {"url": payload["preview_url"]}})
            parts.extend(self._custom_data_parts_from_tool_output(output))
            return parts

        if event_type == "plan_steps":
            return [
                *self._ensure_started(""),
                {"type": "data-plan-steps", "data": {"steps": payload.get("steps") or []}},
            ]

        if event_type == "error":
            return [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                {"type": "error", "errorText": str(payload.get("message") or "Unknown stream error")},
            ]

        if event_type.startswith("data-"):
            return [
                *self._ensure_started(str(payload.get("assistant_id") or "")),
                {"type": event_type, "data": payload.get("data", payload)},
            ]

        return []

    def finish_if_needed(self) -> list[dict[str, Any]]:
        if self.message_id is None:
            return []
        return [
            *self._close_reasoning(),
            *self._close_text(),
            *self._finish_step(),
            {"type": "finish"},
        ]

    def _ensure_started(self, preferred_message_id: str) -> list[dict[str, Any]]:
        if self.message_id is not None:
            return []
        message_id = preferred_message_id.strip() or "assistant-message"
        self.message_id = message_id
        self.step_started = True
        return [
            {"type": "start", "messageId": message_id},
            {"type": "start-step"},
        ]

    def _ensure_text_started(self) -> list[dict[str, Any]]:
        if self.text_open:
            return []
        self.text_index += 1
        self.text_id = f"text_{self._safe_id(self.message_id)}_{self.text_index}"
        self.text_open = True
        return [{"type": "text-start", "id": self.text_id}]

    def _close_text(self) -> list[dict[str, Any]]:
        if not self.text_open or self.text_id is None:
            return []
        text_id = self.text_id
        self.text_open = False
        self.text_id = None
        return [{"type": "text-end", "id": text_id}]

    def _ensure_reasoning_started(self) -> list[dict[str, Any]]:
        if self.reasoning_open:
            return []
        self.reasoning_index += 1
        self.reasoning_id = f"reasoning_{self._safe_id(self.message_id)}_{self.reasoning_index}"
        self.reasoning_open = True
        self.reasoning_text = ""
        return [{"type": "reasoning-start", "id": self.reasoning_id}]

    def _close_reasoning(self) -> list[dict[str, Any]]:
        if not self.reasoning_open or self.reasoning_id is None:
            return []
        reasoning_id = self.reasoning_id
        self.reasoning_open = False
        self.reasoning_id = None
        return [{"type": "reasoning-end", "id": reasoning_id}]

    def _finish_step(self) -> list[dict[str, Any]]:
        if not self.step_started:
            return []
        self.step_started = False
        return [{"type": "finish-step"}]

    def _custom_data_parts_from_tool_output(self, output: Any) -> list[dict[str, Any]]:
        if not isinstance(output, dict):
            return []

        raw_type = output.get("type")
        if isinstance(raw_type, str) and raw_type.startswith("data-"):
            return [{"type": raw_type, "data": output.get("data", {})}]

        raw_data_parts = output.get("data_parts")
        if not isinstance(raw_data_parts, list):
            raw_data_parts = [output.get("data_part")]

        parts: list[dict[str, Any]] = []
        for item in raw_data_parts:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if isinstance(item_type, str) and item_type.startswith("data-"):
                parts.append({"type": item_type, "data": item.get("data", {})})
        return parts

    def _tool_input_parts(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: Any,
        replay_as_deltas: bool = False,
    ) -> list[dict[str, Any]]:
        input_payload = arguments if isinstance(arguments, dict) else {}
        streamed_text = (
            self._streamable_tool_input_text(tool_name, input_payload)
            if replay_as_deltas
            else ""
        )

        parts: list[dict[str, Any]] = []
        if streamed_text:
            parts.append(
                {
                    "type": "tool-input-start",
                    "toolCallId": tool_call_id,
                    "toolName": tool_name,
                }
            )
            for chunk in self._chunk_text(streamed_text):
                parts.append(
                    {
                        "type": "tool-input-delta",
                        "toolCallId": tool_call_id,
                        "inputTextDelta": chunk,
                    }
                )

        parts.append(
            {
                "type": "tool-input-available",
                "toolCallId": tool_call_id,
                "toolName": tool_name,
                "input": input_payload,
                "providerExecuted": False,
                "dynamic": True,
            }
        )
        return parts

    def _streamable_tool_input_text(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "write_file":
            content = arguments.get("content")
            return content if isinstance(content, str) else ""

        if tool_name == "replace_file":
            new_content = arguments.get("new_content")
            if isinstance(new_content, str) and new_content:
                return new_content
            old_content = arguments.get("old_content")
            return old_content if isinstance(old_content, str) else ""

        return ""

    def _chunk_text(self, text: str, chunk_size: int = 96) -> list[str]:
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]

    def _safe_id(self, value: str | None) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "message").strip("_")
        return sanitized or "message"
