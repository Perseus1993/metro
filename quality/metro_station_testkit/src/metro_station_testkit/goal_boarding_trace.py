"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GoalBoardingTraceStep:
    index: int
    time_seconds: float
    event_kind: str
    before_graph_state: str
    after_graph_state: str
    committed_facility_id: str | None
    commands: tuple[str, ...]
    position: tuple[float, float]
    passenger_state: str
    train_state: str
    train_load: int
    train_capacity_remaining: int
    blocker_count: int
    door_queues: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GoalBoardingProbeResult:
    scenario_id: str
    status: str
    final_state: dict[str, Any]
    final_passenger_state: str
    elapsed_seconds: float
    traces: tuple[GoalBoardingTraceStep, ...]
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
            "boarding_service_events": int(self.movement["boarding_service_events"]),
            "boarded_persons": int(self.movement["boarded_persons"]),
        }
