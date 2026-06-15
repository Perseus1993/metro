from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


Point = tuple[float, float]


class AgentIntent(StrEnum):
    ENTER_AND_BOARD = "enter_and_board"
    EXIT_STATION = "exit_station"
    TRANSFER = "transfer"


class FacilityStage(StrEnum):
    ENTRY_GATE = "entry_gate"
    VERTICAL_TRANSFER = "vertical_transfer"
    BOARDING_DOOR = "boarding_door"
    EXIT_GATE = "exit_gate"


class RouteKey(StrEnum):
    CURRENT_POSITION = "current_position"
    ENTRY_GATE_DECISION = "entry_gate_decision"
    AFTER_GATE = "after_gate"
    AFTER_VERTICAL = "after_vertical"
    PLATFORM_TO_VERTICAL = "platform_to_vertical"
    AFTER_EXIT_VERTICAL = "after_exit_vertical"


class PlanActionKind(StrEnum):
    CHOOSE_FACILITY = "choose_facility"
    CHOOSE_PLATFORM = "choose_platform"
    WALK_ROUTE = "walk_route"
    JOIN_PLATFORM = "join_platform"
    DEPART = "depart"


class AgentState(StrEnum):
    ENTERING_STATION = "entering_station"
    CHOOSING_GATE = "choosing_gate"
    QUEUEING_GATE = "queueing_gate"
    PASSING_GATE = "passing_gate"
    WALKING_TO_VERTICAL = "walking_to_vertical"
    CHOOSING_VERTICAL = "choosing_vertical"
    QUEUEING_VERTICAL = "queueing_vertical"
    RIDING_VERTICAL = "riding_vertical"
    WALKING_TO_PLATFORM = "walking_to_platform"
    WAITING_PLATFORM = "waiting_platform"
    QUEUEING_DOOR = "queueing_door"
    BOARDING_TRAIN = "boarding_train"
    WALKING_TO_EXIT_GATE = "walking_to_exit_gate"
    CHOOSING_EXIT_GATE = "choosing_exit_gate"
    QUEUEING_EXIT_GATE = "queueing_exit_gate"
    PASSING_EXIT_GATE = "passing_exit_gate"
    WALKING_TO_TRANSFER = "walking_to_transfer"
    DEPARTED = "departed"


PASSIVE_STATES = {
    AgentState.QUEUEING_GATE.value,
    AgentState.QUEUEING_VERTICAL.value,
    AgentState.WAITING_PLATFORM.value,
    AgentState.QUEUEING_DOOR.value,
    AgentState.BOARDING_TRAIN.value,
    AgentState.QUEUEING_EXIT_GATE.value,
    AgentState.DEPARTED.value,
}


WALKING_STATES = {
    AgentState.ENTERING_STATION.value,
    AgentState.WALKING_TO_VERTICAL.value,
    AgentState.WALKING_TO_PLATFORM.value,
    AgentState.WALKING_TO_EXIT_GATE.value,
    AgentState.WALKING_TO_TRANSFER.value,
}


SERVICE_STATES = {
    AgentState.PASSING_GATE.value,
    AgentState.RIDING_VERTICAL.value,
    AgentState.BOARDING_TRAIN.value,
    AgentState.PASSING_EXIT_GATE.value,
}


CROWD_INTERACTION_STATES = {
    *WALKING_STATES,
    AgentState.QUEUEING_DOOR.value,
}


@dataclass(frozen=True)
class AgentGoal:
    kind: str
    label: str
    target: Point | None = None
    facility_id: str | None = None
    stage: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "target": self.target,
            "facility_id": self.facility_id,
            "stage": self.stage,
        }


@dataclass(frozen=True)
class PlanAction:
    kind: str
    label: str
    trigger_state: str | None = None
    stage: str | None = None
    route_key: str | None = None
    next_state: str | None = None
    completed_stage: str | None = None
    counts_boarded: bool = False


@dataclass
class AgentPlan:
    intent: str
    facility_chain: tuple[str, ...]
    initial_state: str = AgentState.ENTERING_STATION.value
    initial_route_key: str = RouteKey.ENTRY_GATE_DECISION.value
    initial_goal_label: str = "entry gate decision"
    route_arrivals: dict[str, PlanAction] = field(default_factory=dict)
    service_arrivals: dict[str, PlanAction] = field(default_factory=dict)
    action_sequence: tuple[PlanAction, ...] = ()
    action_index: int = 0
    stage_index: int = 0
    chosen_facilities: dict[str, str] = field(default_factory=dict)
    current_goal: AgentGoal = field(
        default_factory=lambda: AgentGoal(kind="idle", label="not_started")
    )

    @classmethod
    def enter_and_board(cls) -> "AgentPlan":
        return cls(
            intent=AgentIntent.ENTER_AND_BOARD.value,
            facility_chain=(
                FacilityStage.ENTRY_GATE.value,
                FacilityStage.VERTICAL_TRANSFER.value,
                FacilityStage.BOARDING_DOOR.value,
            ),
            route_arrivals={
                AgentState.ENTERING_STATION.value: PlanAction(
                    kind=PlanActionKind.CHOOSE_FACILITY.value,
                    label="entry gate decision",
                    stage=FacilityStage.ENTRY_GATE.value,
                    next_state=AgentState.CHOOSING_GATE.value,
                ),
                AgentState.WALKING_TO_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.CHOOSE_FACILITY.value,
                    label="vertical transfer decision",
                    stage=FacilityStage.VERTICAL_TRANSFER.value,
                    next_state=AgentState.CHOOSING_VERTICAL.value,
                ),
                AgentState.WALKING_TO_PLATFORM.value: PlanAction(
                    kind=PlanActionKind.JOIN_PLATFORM.value,
                    label="platform waiting area",
                ),
            },
            service_arrivals={
                AgentState.PASSING_GATE.value: PlanAction(
                    kind=PlanActionKind.WALK_ROUTE.value,
                    label="vertical transfer decision",
                    route_key=RouteKey.AFTER_GATE.value,
                    next_state=AgentState.WALKING_TO_VERTICAL.value,
                    completed_stage=FacilityStage.ENTRY_GATE.value,
                ),
                AgentState.RIDING_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.WALK_ROUTE.value,
                    label="platform waiting area",
                    route_key=RouteKey.AFTER_VERTICAL.value,
                    next_state=AgentState.WALKING_TO_PLATFORM.value,
                    completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
                ),
                AgentState.BOARDING_TRAIN.value: PlanAction(
                    kind=PlanActionKind.DEPART.value,
                    label="boarded train",
                    completed_stage=FacilityStage.BOARDING_DOOR.value,
                    counts_boarded=True,
                ),
            },
        )

    @classmethod
    def exit_station(cls) -> "AgentPlan":
        return cls(
            intent=AgentIntent.EXIT_STATION.value,
            facility_chain=(
                FacilityStage.VERTICAL_TRANSFER.value,
                FacilityStage.EXIT_GATE.value,
            ),
            initial_state=AgentState.WALKING_TO_VERTICAL.value,
            initial_route_key=RouteKey.PLATFORM_TO_VERTICAL.value,
            initial_goal_label="vertical transfer decision",
            route_arrivals={
                AgentState.WALKING_TO_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.CHOOSE_FACILITY.value,
                    label="vertical transfer decision",
                    stage=FacilityStage.VERTICAL_TRANSFER.value,
                    next_state=AgentState.CHOOSING_VERTICAL.value,
                ),
                AgentState.WALKING_TO_EXIT_GATE.value: PlanAction(
                    kind=PlanActionKind.CHOOSE_FACILITY.value,
                    label="exit gate decision",
                    stage=FacilityStage.EXIT_GATE.value,
                    next_state=AgentState.CHOOSING_EXIT_GATE.value,
                ),
            },
            service_arrivals={
                AgentState.RIDING_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.WALK_ROUTE.value,
                    label="exit gate decision",
                    route_key=RouteKey.AFTER_EXIT_VERTICAL.value,
                    next_state=AgentState.WALKING_TO_EXIT_GATE.value,
                    completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
                ),
                AgentState.PASSING_EXIT_GATE.value: PlanAction(
                    kind=PlanActionKind.DEPART.value,
                    label="left station",
                    completed_stage=FacilityStage.EXIT_GATE.value,
                ),
            },
        )

    @classmethod
    def transfer(cls) -> "AgentPlan":
        return cls(
            intent=AgentIntent.TRANSFER.value,
            facility_chain=(
                FacilityStage.VERTICAL_TRANSFER.value,
                FacilityStage.BOARDING_DOOR.value,
            ),
            initial_state=AgentState.WALKING_TO_VERTICAL.value,
            initial_route_key=RouteKey.PLATFORM_TO_VERTICAL.value,
            initial_goal_label="transfer vertical decision",
            route_arrivals={
                AgentState.WALKING_TO_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.CHOOSE_FACILITY.value,
                    label="transfer vertical decision",
                    stage=FacilityStage.VERTICAL_TRANSFER.value,
                    next_state=AgentState.CHOOSING_VERTICAL.value,
                ),
                AgentState.WALKING_TO_PLATFORM.value: PlanAction(
                    kind=PlanActionKind.JOIN_PLATFORM.value,
                    label="transfer platform waiting area",
                ),
            },
            service_arrivals={
                AgentState.RIDING_VERTICAL.value: PlanAction(
                    kind=PlanActionKind.WALK_ROUTE.value,
                    label="transfer platform waiting area",
                    route_key=RouteKey.AFTER_VERTICAL.value,
                    next_state=AgentState.WALKING_TO_PLATFORM.value,
                    completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
                ),
                AgentState.BOARDING_TRAIN.value: PlanAction(
                    kind=PlanActionKind.DEPART.value,
                    label="boarded transfer train",
                    completed_stage=FacilityStage.BOARDING_DOOR.value,
                    counts_boarded=True,
                ),
            },
        )

    @classmethod
    def for_intent(cls, intent: str | AgentIntent) -> "AgentPlan":
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        if intent_value == AgentIntent.EXIT_STATION.value:
            return cls.exit_station()
        if intent_value == AgentIntent.TRANSFER.value:
            return cls.transfer()
        return cls.enter_and_board()

    def current_stage(self) -> str | None:
        if self.stage_index >= len(self.facility_chain):
            return None
        return self.facility_chain[self.stage_index]

    def __post_init__(self) -> None:
        overlapping_states = set(self.route_arrivals).intersection(self.service_arrivals)
        if overlapping_states:
            joined = ", ".join(sorted(overlapping_states))
            raise ValueError(f"Plan states cannot be both route and service arrivals: {joined}")

    def action_for_reached_state(self, state: str | AgentState) -> PlanAction | None:
        state_value = state.value if isinstance(state, AgentState) else str(state)
        if self.action_sequence:
            if self.action_index >= len(self.action_sequence):
                return None
            action = self.action_sequence[self.action_index]
            if action.trigger_state is None or action.trigger_state == state_value:
                return action
            return None
        return self.service_arrivals.get(state_value) or self.route_arrivals.get(state_value)

    def advance_action(self, action: PlanAction) -> None:
        if (
            self.action_sequence
            and self.action_index < len(self.action_sequence)
            and self.action_sequence[self.action_index] == action
        ):
            self.action_index += 1

    def align_to_trigger_state(self, state: str | AgentState) -> None:
        if not self.action_sequence:
            return
        state_value = state.value if isinstance(state, AgentState) else str(state)
        if self.action_index < len(self.action_sequence):
            current = self.action_sequence[self.action_index]
            if current.trigger_state is None or current.trigger_state == state_value:
                return
        for index in range(self.action_index, len(self.action_sequence)):
            if self.action_sequence[index].trigger_state == state_value:
                self.action_index = index
                return

    def assign_facility(self, stage: str | FacilityStage, facility_id: str) -> None:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        self.chosen_facilities[stage_value] = facility_id

    def complete_stage(self, stage: str | FacilityStage) -> None:
        stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
        if self.current_stage() == stage_value:
            self.stage_index += 1

    def set_goal(
        self,
        *,
        kind: str,
        label: str,
        target: Point | None = None,
        facility_id: str | None = None,
        stage: str | FacilityStage | None = None,
    ) -> None:
        self.current_goal = AgentGoal(
            kind=kind,
            label=label,
            target=target,
            facility_id=facility_id,
            stage=None
            if stage is None
            else stage.value
            if isinstance(stage, FacilityStage)
            else str(stage),
        )
