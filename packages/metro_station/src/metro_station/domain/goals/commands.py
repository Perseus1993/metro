from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class GoalCommandKind(StrEnum):
    OBSERVE_CANDIDATES = "observe_candidates"
    SELECT_FACILITY = "select_facility"
    WALK_TO_REGION = "walk_to_region"
    WALK_TO_QUEUE = "walk_to_queue"
    JOIN_QUEUE = "join_queue"
    WAIT_FOR_SERVICE = "wait_for_service"
    USE_FACILITY = "use_facility"
    WAIT_FOR_EVENT = "wait_for_event"
    REPLAN_STAGE = "replan_stage"
    COMPLETE_JOURNEY = "complete_journey"


@dataclass(frozen=True)
class GoalCommand:
    kind: str
    command_id: str | None = None
    goal_node_id: str | None = None
    stage: str | None = None
    event_kind: str | None = None
    target_region_id: str | None = None
    facility_id: str | None = None
    reason: str | None = None
    selection_action: str | None = None
    decision_evidence: dict[str, Any] = field(default_factory=dict)
    replan_cleanup_only: bool = False

    def __post_init__(self) -> None:
        try:
            kind = GoalCommandKind(self.kind)
        except ValueError as exc:
            raise ValueError(f"unsupported goal command kind {self.kind!r}") from exc
        for field_name in ("command_id", "goal_node_id", "stage", "event_kind"):
            value = getattr(self, field_name)
            if value is not None and not value.strip():
                raise ValueError(f"goal command {field_name} cannot be blank")
        if kind == GoalCommandKind.WALK_TO_REGION and not self.target_region_id:
            raise ValueError("walk-to-region command requires target_region_id")
        if kind in _FACILITY_COMMAND_KINDS and not self.facility_id:
            raise ValueError(f"goal command {kind.value!r} requires facility_id")
        if kind == GoalCommandKind.REPLAN_STAGE and not self.reason:
            raise ValueError("replan-stage command requires reason")
        if self.selection_action not in {None, "select", "retain", "switch"}:
            raise ValueError("selection_action must be select, retain, or switch")
        if self.selection_action is not None and kind != GoalCommandKind.SELECT_FACILITY:
            raise ValueError("selection_action is only valid for select-facility commands")
        if self.replan_cleanup_only and kind != GoalCommandKind.REPLAN_STAGE:
            raise ValueError("replan_cleanup_only is only valid for replan-stage commands")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_FACILITY_COMMAND_KINDS = {
    GoalCommandKind.SELECT_FACILITY,
    GoalCommandKind.WALK_TO_QUEUE,
    GoalCommandKind.JOIN_QUEUE,
    GoalCommandKind.WAIT_FOR_SERVICE,
    GoalCommandKind.USE_FACILITY,
}
