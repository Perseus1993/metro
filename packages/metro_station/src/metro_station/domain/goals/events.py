from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from math import isfinite
from typing import Any


class GoalEventKind(StrEnum):
    JOURNEY_STARTED = "journey_started"
    ENTERED_REGION = "entered_region"
    CANDIDATES_UPDATED = "candidates_updated"
    FACILITY_SELECTED = "facility_selected"
    REACHED_QUEUE_CAPTURE = "reached_queue_capture"
    QUEUE_JOINED = "queue_joined"
    SERVICE_STARTED = "service_started"
    SERVICE_COMPLETED = "service_completed"
    FACILITY_UNAVAILABLE = "facility_unavailable"
    PROGRESS_STALLED = "progress_stalled"
    WAIT_TIMEOUT = "wait_timeout"
    TRAIN_AVAILABLE = "train_available"
    TRAIN_FULL = "train_full"
    TRAIN_DEPARTED = "train_departed"
    TERMINAL_REACHED = "terminal_reached"
    GOAL_COMPLETED = "goal_completed"


@dataclass(frozen=True)
class FacilityObservation:
    facility_id: str
    stage: str
    available: bool
    reachable: bool
    walking_time_seconds: float
    queue_persons: int
    estimated_wait_seconds: float
    local_density_persons_m2: float = 0.0
    service_state: str = "unknown"
    service_time_seconds: float = 0.0
    walking_distance_units: float | None = None
    walking_cost_source: str = "unspecified"
    preference_penalty_seconds: float = 0.0
    guidance_adjustment_seconds: float = 0.0
    avoidance_penalty_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.facility_id.strip() or not self.stage.strip():
            raise ValueError("facility observation requires facility_id and stage")
        numeric_values = (
            self.walking_time_seconds,
            self.estimated_wait_seconds,
            self.local_density_persons_m2,
            self.service_time_seconds,
            self.preference_penalty_seconds,
            self.avoidance_penalty_seconds,
        )
        if any(not isfinite(value) or value < 0 for value in numeric_values):
            raise ValueError("facility observation values cannot be negative")
        if self.queue_persons < 0:
            raise ValueError("facility observation values cannot be negative")
        if not isfinite(self.guidance_adjustment_seconds):
            raise ValueError("facility guidance adjustment must be finite")
        if self.walking_distance_units is not None and (
            not isfinite(self.walking_distance_units) or self.walking_distance_units < 0
        ):
            raise ValueError("facility walking distance must be finite and non-negative")
        if not self.walking_cost_source.strip():
            raise ValueError("facility walking cost source cannot be blank")


@dataclass(frozen=True)
class DecisionObservation:
    time_seconds: float
    current_region_id: str | None
    entered_region_ids: tuple[str, ...] = ()
    candidates: tuple[FacilityObservation, ...] = ()
    committed_facility_id: str | None = None
    committed_at_seconds: float | None = None
    reconsider_after_seconds: float | None = None
    replan_reason: str | None = None
    commitment_duration_seconds: float = 15.0
    replan_cooldown_seconds: float = 30.0
    minimum_improvement_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.time_seconds < 0:
            raise ValueError("decision observation time cannot be negative")
        candidate_ids = [candidate.facility_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("decision observation contains duplicate facility candidates")
        policy_values = (
            self.commitment_duration_seconds,
            self.replan_cooldown_seconds,
            self.minimum_improvement_seconds,
        )
        if any(not isfinite(value) or value < 0 for value in policy_values):
            raise ValueError("facility decision policy values must be finite and non-negative")
        if self.committed_facility_id is not None and not self.committed_facility_id.strip():
            raise ValueError("committed_facility_id cannot be blank")
        if self.committed_at_seconds is not None and self.committed_at_seconds < 0:
            raise ValueError("committed_at_seconds cannot be negative")
        if self.reconsider_after_seconds is not None and self.reconsider_after_seconds < 0:
            raise ValueError("reconsider_after_seconds cannot be negative")

    def candidate(self, facility_id: str) -> FacilityObservation | None:
        return next(
            (candidate for candidate in self.candidates if candidate.facility_id == facility_id),
            None,
        )


@dataclass(frozen=True)
class GoalEvent:
    kind: str
    time_seconds: float
    event_id: str | None = None
    command_id: str | None = None
    goal_node_id: str | None = None
    stage: str | None = None
    region_id: str | None = None
    facility_id: str | None = None
    reason: str | None = None
    observation: DecisionObservation | None = None
    train_platform_id: str | None = None
    train_arrival_sequence: int | None = None

    def __post_init__(self) -> None:
        try:
            kind = GoalEventKind(self.kind)
        except ValueError as exc:
            raise ValueError(f"unsupported goal event kind {self.kind!r}") from exc
        if self.time_seconds < 0:
            raise ValueError("goal event time cannot be negative")
        for field_name in ("event_id", "command_id", "goal_node_id", "stage"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"goal event {field_name} cannot be blank")
        if self.train_platform_id is not None and not self.train_platform_id.strip():
            raise ValueError("goal event train_platform_id cannot be blank")
        if (self.train_platform_id is None) != (self.train_arrival_sequence is None):
            raise ValueError(
                "goal event train episode requires both platform id and arrival sequence"
            )
        if self.train_arrival_sequence is not None and self.train_arrival_sequence < 0:
            raise ValueError("goal event train arrival sequence cannot be negative")
        if kind == GoalEventKind.ENTERED_REGION and not self.region_id:
            raise ValueError("entered-region event requires region_id")
        if kind == GoalEventKind.CANDIDATES_UPDATED and self.observation is None:
            raise ValueError("candidates-updated event requires observation")
        if kind in _FACILITY_EVENT_KINDS and not self.facility_id:
            raise ValueError(f"goal event {kind.value!r} requires facility_id")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_FACILITY_EVENT_KINDS = {
    GoalEventKind.REACHED_QUEUE_CAPTURE,
    GoalEventKind.QUEUE_JOINED,
    GoalEventKind.SERVICE_STARTED,
    GoalEventKind.SERVICE_COMPLETED,
    GoalEventKind.FACILITY_UNAVAILABLE,
}
