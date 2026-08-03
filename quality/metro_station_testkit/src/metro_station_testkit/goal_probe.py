"""Goal Graph probe migrated from the planning production namespace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from metro_station.adapters.simulation.planning.default_goal_state_machine import EventDrivenGoalStateMachine
from metro_station.adapters.simulation.planning.goal_engine import GoalEngineResult
from metro_station.adapters.simulation.planning.goal_events import GoalEvent
from metro_station.adapters.simulation.planning.goal_graph import JourneyGraph
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState


@dataclass(frozen=True)
class GoalProbeStep:
    index: int
    time_seconds: float
    event_kind: str
    note: str
    before_node: str | None
    before_interaction: str | None
    before_facility: str | None
    after_node: str
    after_interaction: str | None
    after_facility: str | None
    handled: bool
    commands: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalProbeResult:
    scenario_id: str
    label: str
    expected_outcome: str
    status: str
    final_state: dict[str, Any]
    steps: tuple[GoalProbeStep, ...]
    checks: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.as_dict() for step in self.steps]
        return payload


class GoalProbeRecorder:
    def __init__(
        self,
        *,
        scenario_id: str,
        label: str,
        expected_outcome: str,
        graph: JourneyGraph,
    ) -> None:
        self.scenario_id = scenario_id
        self.label = label
        self.expected_outcome = expected_outcome
        self.graph = graph
        self.machine = EventDrivenGoalStateMachine()
        started = self.machine.start(graph)
        self.state = started.state
        self.steps = [
            self._step(
                event_kind="start",
                time_seconds=0.0,
                note="旅程启动，仅设置模糊决策区目标",
                before=None,
                result=started,
            )
        ]

    def apply(self, event: GoalEvent, note: str) -> AgentGoalState:
        before = self.state
        result = self.machine.handle(self.graph, before, event)
        self.state = result.state
        self.steps.append(
            self._step(
                event_kind=event.kind,
                time_seconds=event.time_seconds,
                note=note,
                before=before,
                result=result,
            )
        )
        return self.state

    def finish(self, checks: dict[str, bool]) -> GoalProbeResult:
        return GoalProbeResult(
            scenario_id=self.scenario_id,
            label=self.label,
            expected_outcome=self.expected_outcome,
            status="ok" if checks and all(checks.values()) else "review",
            final_state=self.state.as_dict(),
            steps=tuple(self.steps),
            checks=checks,
        )

    def _step(
        self,
        *,
        event_kind: str,
        time_seconds: float,
        note: str,
        before: AgentGoalState | None,
        result: GoalEngineResult,
    ) -> GoalProbeStep:
        return GoalProbeStep(
            index=len(self.steps) if hasattr(self, "steps") else 0,
            time_seconds=time_seconds,
            event_kind=event_kind,
            note=note,
            before_node=None if before is None else before.current_node_id,
            before_interaction=None if before is None else before.interaction_state,
            before_facility=_facility_id(before),
            after_node=result.state.current_node_id,
            after_interaction=result.state.interaction_state,
            after_facility=_facility_id(result.state),
            handled=result.handled,
            commands=tuple(command.as_dict() for command in result.commands),
        )


def _facility_id(state: AgentGoalState | None) -> str | None:
    if state is None or state.commitment is None:
        return None
    return state.commitment.facility_id
