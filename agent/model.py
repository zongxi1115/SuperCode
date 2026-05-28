from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .schema import AgentState


@dataclass(slots=True)
class ModelStep:
    """One model response normalized into the next agent step.

    A step is either:
    - a request to call one or more tools
    - a final text response for the user
    """

    action: str
    thought: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None
    provider_response_items: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def call_tool(
        cls,
        thought: str,
        tool_name: str,
        tool_arguments: dict[str, Any] | None = None,
    ) -> "ModelStep":
        return cls(
            action="tool",
            thought=thought,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
        )

    @classmethod
    def call_tools(
        cls,
        thought: str,
        tool_calls: list[dict[str, Any]],
    ) -> "ModelStep":
        if not tool_calls:
            raise ValueError("tool_calls 不能为空。")

        first_tool = tool_calls[0]
        return cls(
            action="tool",
            thought=thought,
            tool_name=str(first_tool.get("tool_name", "")).strip() or None,
            tool_arguments=first_tool.get("tool_arguments", {}) or {},
            tool_calls=tool_calls,
        )

    @classmethod
    def finish(cls, thought: str, final_answer: str) -> "ModelStep":
        return cls(action="final", thought=thought, final_answer=final_answer)

    @property
    def text(self) -> str:
        return self.final_answer or ""

    def normalized_tool_calls(self) -> list[dict[str, Any]]:
        if self.tool_calls:
            return self.tool_calls
        if self.tool_name is None:
            return []
        return [
            {
                "tool_name": self.tool_name,
                "tool_arguments": self.tool_arguments,
            }
        ]


@dataclass(slots=True)
class ModelStreamUpdate:
    """Streaming state emitted while the model is building a step."""

    raw_output: str
    action: str | None = None
    thought: str | None = None
    tool_name: str | None = None
    final_answer: str | None = None
    streamed_tool_name: str | None = None
    streamed_tool_argument_name: str | None = None
    streamed_tool_input: str | None = None


class ModelAdapter(ABC):
    """Adapter between the agent runtime and a model provider.

    The runtime owns the agent loop. The adapter only turns state and tool
    schemas into the model's next normalized step.
    """

    @abstractmethod
    def next_step(
        self,
        state: AgentState,
        tool_definitions: dict[str, dict[str, Any]],
        on_stream: Callable[[ModelStreamUpdate], None] | None = None,
    ) -> ModelStep:
        """Return the next model step for the current agent state."""

    def latest_usage(self) -> dict[str, int] | None:
        return None


__all__ = [
    "ModelAdapter",
    "ModelStep",
    "ModelStreamUpdate",
]
