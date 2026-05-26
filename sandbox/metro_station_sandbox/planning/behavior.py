from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import hypot
from typing import TYPE_CHECKING, Any

from .plan import AgentIntent, AgentState, FacilityStage

if TYPE_CHECKING:
    from ..agents import PassengerAgent


class BehaviorActionKind(StrEnum):
    """Human-readable passenger behavior layer above low-level agent states."""

    WALK_TO_REGION = "walk_to_region"
    CHOOSE_FACILITY = "choose_facility"
    WALK_TO_QUEUE_TAIL = "walk_to_queue_tail"
    WAIT_IN_QUEUE = "wait_in_queue"
    WAIT_IN_REGION = "wait_in_region"
    USE_FACILITY = "use_facility"
    BOARD_TRAIN = "board_train"
    DEPART = "depart"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RegionGoal:
    """Origin/destination intent expressed as station regions, not coordinates."""

    intent: str
    origin_region: str
    destination_region: str
    via_regions: tuple[str, ...] = ()
    target_line_id: str | None = None
    target_direction: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "origin_region": self.origin_region,
            "destination_region": self.destination_region,
            "via_regions": list(self.via_regions),
            "target_line_id": self.target_line_id,
            "target_direction": self.target_direction,
        }


@dataclass(frozen=True)
class BehaviorStatus:
    """Debug snapshot for why a passenger is moving or waiting right now."""

    action: str
    region_goal: RegionGoal
    current_region: str
    target_region: str | None = None
    facility_id: str | None = None
    facility_stage: str | None = None
    queue_mode: str | None = None
    progress_age_seconds: float | None = None
    last_replan_reason: str | None = None
    distance_to_target: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "region_goal": self.region_goal.as_dict(),
            "current_region": self.current_region,
            "target_region": self.target_region,
            "facility_id": self.facility_id,
            "facility_stage": self.facility_stage,
            "queue_mode": self.queue_mode,
            "progress_age_seconds": self.progress_age_seconds,
            "last_replan_reason": self.last_replan_reason,
            "distance_to_target": self.distance_to_target,
        }


QUEUE_STATES = {
    AgentState.QUEUEING_GATE.value,
    AgentState.QUEUEING_VERTICAL.value,
    AgentState.QUEUEING_DOOR.value,
    AgentState.QUEUEING_EXIT_GATE.value,
}

CHOICE_STATES = {
    AgentState.CHOOSING_GATE.value,
    AgentState.CHOOSING_VERTICAL.value,
    AgentState.CHOOSING_EXIT_GATE.value,
}

SERVICE_STATES = {
    AgentState.PASSING_GATE.value,
    AgentState.RIDING_VERTICAL.value,
    AgentState.PASSING_EXIT_GATE.value,
}

WALKING_STATES = {
    AgentState.ENTERING_STATION.value,
    AgentState.WALKING_TO_VERTICAL.value,
    AgentState.WALKING_TO_PLATFORM.value,
    AgentState.WALKING_TO_EXIT_GATE.value,
    AgentState.WALKING_TO_TRANSFER.value,
}


def region_goal_for_passenger(passenger: PassengerAgent) -> RegionGoal:
    intent = str(passenger.intent)
    target_line_id = passenger.target_line_id or passenger.assigned_line_id
    target_direction = passenger.target_direction or passenger.assigned_direction
    if intent == AgentIntent.EXIT_STATION.value:
        return RegionGoal(
            intent=intent,
            origin_region="train_platform",
            destination_region="station_exit",
            via_regions=("vertical_transfer", "exit_gate"),
            target_line_id=target_line_id,
            target_direction=target_direction,
        )
    if intent == AgentIntent.TRANSFER.value:
        return RegionGoal(
            intent=intent,
            origin_region="source_platform",
            destination_region="target_train",
            via_regions=("transfer_path", "target_platform", "boarding_door"),
            target_line_id=target_line_id,
            target_direction=target_direction,
        )
    return RegionGoal(
        intent=intent,
        origin_region="station_entrance",
        destination_region="train_interior",
        via_regions=("entry_gate", "vertical_transfer", "platform", "boarding_door"),
        target_line_id=target_line_id,
        target_direction=target_direction,
    )


def behavior_status_for_passenger(passenger: PassengerAgent) -> BehaviorStatus:
    state = str(passenger.state)
    goal = passenger.current_goal
    facility_stage = goal.stage
    facility_id = passenger.assigned_facility_id or goal.facility_id
    action = _action_for_state(state, goal.kind)
    current_region = _current_region_for_state(state, facility_stage)
    target_region = _target_region_for_state(state, facility_stage, goal.label)
    queue_mode = _queue_mode_for_state(state, goal.kind)
    distance_to_target = _distance_to_target(passenger)
    return BehaviorStatus(
        action=action,
        region_goal=region_goal_for_passenger(passenger),
        current_region=current_region,
        target_region=target_region,
        facility_id=facility_id,
        facility_stage=facility_stage,
        queue_mode=queue_mode,
        progress_age_seconds=getattr(passenger, "progress_age_seconds", None),
        last_replan_reason=getattr(passenger, "last_replan_reason", None),
        distance_to_target=distance_to_target,
    )


def _action_for_state(state: str, goal_kind: str | None) -> str:
    if state == AgentState.DEPARTED.value:
        return BehaviorActionKind.DEPART.value
    if state == AgentState.BOARDING_TRAIN.value:
        return BehaviorActionKind.BOARD_TRAIN.value
    if state == AgentState.WAITING_PLATFORM.value:
        return BehaviorActionKind.WAIT_IN_REGION.value
    if state in QUEUE_STATES:
        return BehaviorActionKind.WAIT_IN_QUEUE.value
    if state in CHOICE_STATES:
        return BehaviorActionKind.CHOOSE_FACILITY.value
    if state in SERVICE_STATES:
        return BehaviorActionKind.USE_FACILITY.value
    if state in WALKING_STATES:
        if goal_kind == "queued":
            return BehaviorActionKind.WALK_TO_QUEUE_TAIL.value
        return BehaviorActionKind.WALK_TO_REGION.value
    return BehaviorActionKind.UNKNOWN.value


def _current_region_for_state(state: str, facility_stage: str | None) -> str:
    if state == AgentState.ENTERING_STATION.value:
        return "station_entrance"
    if state in {
        AgentState.CHOOSING_GATE.value,
        AgentState.QUEUEING_GATE.value,
    }:
        return "unpaid_concourse"
    if state == AgentState.PASSING_GATE.value:
        return "entry_gate"
    if state in {
        AgentState.WALKING_TO_VERTICAL.value,
        AgentState.CHOOSING_VERTICAL.value,
        AgentState.QUEUEING_VERTICAL.value,
    }:
        return "paid_concourse"
    if state == AgentState.RIDING_VERTICAL.value:
        return "vertical_transfer"
    if state in {
        AgentState.WALKING_TO_PLATFORM.value,
        AgentState.WAITING_PLATFORM.value,
        AgentState.QUEUEING_DOOR.value,
        AgentState.BOARDING_TRAIN.value,
    }:
        return "platform"
    if state in {
        AgentState.WALKING_TO_EXIT_GATE.value,
        AgentState.CHOOSING_EXIT_GATE.value,
        AgentState.QUEUEING_EXIT_GATE.value,
    }:
        return "exit_concourse"
    if state == AgentState.PASSING_EXIT_GATE.value:
        return "exit_gate"
    if state == AgentState.WALKING_TO_TRANSFER.value:
        return "transfer_path"
    if state == AgentState.DEPARTED.value:
        return "outside_or_train"
    return _region_for_facility_stage(facility_stage) or "unknown"


def _target_region_for_state(
    state: str,
    facility_stage: str | None,
    goal_label: str | None,
) -> str | None:
    if facility_stage is not None:
        return _region_for_facility_stage(facility_stage)
    if state == AgentState.WALKING_TO_PLATFORM.value:
        return "platform_waiting_area"
    if state == AgentState.WALKING_TO_TRANSFER.value:
        return "transfer_path"
    if state == AgentState.DEPARTED.value:
        return None
    if goal_label:
        label = goal_label.lower()
        if "platform" in label:
            return "platform_waiting_area"
        if "vertical" in label:
            return "vertical_transfer"
        if "exit" in label:
            return "station_exit"
        if "gate" in label:
            return "entry_gate"
    return None


def _region_for_facility_stage(stage: str | None) -> str | None:
    if stage == FacilityStage.ENTRY_GATE.value:
        return "entry_gate"
    if stage == FacilityStage.VERTICAL_TRANSFER.value:
        return "vertical_transfer"
    if stage == FacilityStage.BOARDING_DOOR.value:
        return "boarding_door"
    if stage == FacilityStage.EXIT_GATE.value:
        return "exit_gate"
    return None


def _queue_mode_for_state(state: str, goal_kind: str | None) -> str | None:
    if state in QUEUE_STATES:
        return "enqueued"
    if goal_kind == "queued":
        return "targeting"
    return None


def _distance_to_target(passenger: PassengerAgent) -> float | None:
    target = getattr(passenger, "target", None)
    pos = getattr(passenger, "pos", None)
    if target is None or pos is None:
        return None
    return round(hypot(float(target[0]) - float(pos[0]), float(target[1]) - float(pos[1])), 3)
