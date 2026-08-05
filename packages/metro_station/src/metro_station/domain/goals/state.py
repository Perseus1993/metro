from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class FacilityInteractionState(StrEnum):
    APPROACH_DECISION_REGION = "approach_decision_region"
    EVALUATE_CANDIDATES = "evaluate_candidates"
    WAITING_CAPACITY = "waiting_capacity"
    COMMITTED = "committed"
    APPROACH_QUEUE = "approach_queue"
    CAPTURE_QUEUE = "capture_queue"
    QUEUEING = "queueing"
    IN_SERVICE = "in_service"
    RELEASED = "released"
    COMPLETED = "completed"
    REPLAN_PENDING = "replan_pending"


PRE_SERVICE_REPLAN_STATES = frozenset(
    {
        FacilityInteractionState.COMMITTED.value,
        FacilityInteractionState.APPROACH_QUEUE.value,
        FacilityInteractionState.CAPTURE_QUEUE.value,
        FacilityInteractionState.QUEUEING.value,
    }
)


@dataclass(frozen=True)
class FacilityCommitment:
    facility_id: str
    committed_at_seconds: float
    reason: str
    generalized_cost_seconds: float | None = None
    reconsider_after_seconds: float | None = None
    valid_until_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.facility_id.strip():
            raise ValueError("facility commitment requires facility_id")
        if self.committed_at_seconds < 0:
            raise ValueError("facility commitment time cannot be negative")
        if not self.reason.strip():
            raise ValueError("facility commitment requires reason")
        if self.generalized_cost_seconds is not None and self.generalized_cost_seconds < 0:
            raise ValueError("facility generalized cost cannot be negative")
        if (
            self.reconsider_after_seconds is not None
            and self.reconsider_after_seconds < self.committed_at_seconds
        ):
            raise ValueError("reconsider_after_seconds cannot precede commitment")
        if (
            self.valid_until_seconds is not None
            and self.valid_until_seconds < self.committed_at_seconds
        ):
            raise ValueError("valid_until_seconds cannot precede commitment")


@dataclass(frozen=True)
class AgentGoalState:
    journey_graph_id: str
    journey_graph_version: int
    current_node_id: str
    interaction_state: str | None = None
    current_stage: str | None = None
    commitment: FacilityCommitment | None = None
    queued_facility_id: str | None = None
    replan_origin_interaction_state: str | None = None
    replan_reason: str | None = None
    replan_requested_at_seconds: float | None = None
    transition_count: int = 0
    retry_count: int = 0
    last_event_time_seconds: float = 0.0
    processed_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.journey_graph_id.strip():
            raise ValueError("agent goal state requires journey_graph_id")
        if self.journey_graph_version <= 0:
            raise ValueError("journey_graph_version must be positive")
        if not self.current_node_id.strip():
            raise ValueError("agent goal state requires current_node_id")
        if self.transition_count < 0 or self.retry_count < 0:
            raise ValueError("goal-state counters cannot be negative")
        if self.last_event_time_seconds < 0:
            raise ValueError("last_event_time_seconds cannot be negative")
        if len(self.processed_event_ids) != len(set(self.processed_event_ids)):
            raise ValueError("processed goal event ids must be unique")
        if self.interaction_state is not None:
            FacilityInteractionState(self.interaction_state)
        if self.replan_origin_interaction_state is not None:
            origin = FacilityInteractionState(self.replan_origin_interaction_state)
            if origin not in {
                FacilityInteractionState.COMMITTED,
                FacilityInteractionState.APPROACH_QUEUE,
                FacilityInteractionState.CAPTURE_QUEUE,
                FacilityInteractionState.QUEUEING,
            }:
                raise ValueError("replan origin must be a pre-service interaction state")
        if self.replan_requested_at_seconds is not None and self.replan_requested_at_seconds < 0:
            raise ValueError("replan request time cannot be negative")
        if self.replan_reason is not None and not self.replan_reason.strip():
            raise ValueError("replan reason cannot be blank")
        if self.queued_facility_id is not None:
            if self.commitment is None:
                raise ValueError("queued facility requires an active facility commitment")
            if self.queued_facility_id != self.commitment.facility_id:
                raise ValueError("queued facility must match committed facility")
        if self.interaction_state in _COMMITMENT_REQUIRED_STATES and self.commitment is None:
            raise ValueError(f"interaction state {self.interaction_state!r} requires commitment")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_COMMITMENT_REQUIRED_STATES = {
    FacilityInteractionState.COMMITTED.value,
    FacilityInteractionState.APPROACH_QUEUE.value,
    FacilityInteractionState.CAPTURE_QUEUE.value,
    FacilityInteractionState.QUEUEING.value,
    FacilityInteractionState.IN_SERVICE.value,
    FacilityInteractionState.RELEASED.value,
}
