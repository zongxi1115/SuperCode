from __future__ import annotations

from .schema import AgentState, StepRecord


class AgentStateView:
    """Typed access to framework-owned fields inside AgentState.data."""

    def __init__(self, state: AgentState) -> None:
        self.state = state

    @property
    def step_records(self) -> list[StepRecord]:
        records = self.state.data.setdefault("step_records", [])
        if not isinstance(records, list):
            records = []
            self.state.data["step_records"] = records
        return records

    @property
    def turn_index(self) -> int | None:
        raw_value = self.state.data.get("turn_index")
        if raw_value is None:
            return None
        return int(raw_value)

    def start_turn(self, *, continue_existing_turn: bool, include_thoughts: bool) -> int:
        if continue_existing_turn and self.turn_index is not None:
            turn_index = self.turn_index or 0
        else:
            turn_index = int(self.state.data.get("turn_index", 0)) + 1

        self.state.data["turn_index"] = turn_index
        self.state.data["include_thoughts_in_context"] = include_thoughts
        self.state.tool_results = []
        return turn_index

    def first_step_index(self, turn_index: int, *, continue_existing_turn: bool) -> int:
        if not continue_existing_turn:
            return 1

        current_turn_indices = [
            step.index
            for step in self.step_records
            if isinstance(step, StepRecord) and step.turn_index == turn_index
        ]
        return (max(current_turn_indices) + 1) if current_turn_indices else 1

    def append_step(self, step: StepRecord) -> None:
        self.step_records.append(step)

    @property
    def tool_records(self) -> list[dict[str, object]]:
        records = self.state.data.setdefault("tool_records", [])
        if not isinstance(records, list):
            records = []
            self.state.data["tool_records"] = records
        return records

    @property
    def planning_records(self) -> list[dict[str, object]]:
        records = self.state.data.setdefault("planning_records", [])
        if not isinstance(records, list):
            records = []
            self.state.data["planning_records"] = records
        return records


__all__ = ["AgentStateView"]
