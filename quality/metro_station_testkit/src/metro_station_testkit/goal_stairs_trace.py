"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GoalStairsTraceStep:
    index: int
    time_seconds: float
    event_kind: str
    handled: bool
    before_graph_state: str
    after_graph_state: str
    committed_facility_id: str | None
    commands: tuple[str, ...]
    position: tuple[float, float]
    current_level_id: str
    blocker_count: int
    stair_queues: dict[str, int]
    active_rides: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalStairsProbeResult:
    scenario_id: str
    status: str
    final_state: dict[str, Any]
    final_position: tuple[float, float]
    final_level_id: str
    elapsed_seconds: float
    traces: tuple[GoalStairsTraceStep, ...]
    checks: dict[str, bool]
    movement: dict[str, Any]
    timed_out: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["traces"] = [trace.as_dict() for trace in self.traces]
        return payload

    def summary_metrics(self) -> dict[str, int]:
        return {
            "trace_steps": len(self.traces),
            "jupedsim_steps": int(self.movement["jupedsim_steps"]),
            "vertical_service_events": int(self.movement["vertical_service_events"]),
        }
