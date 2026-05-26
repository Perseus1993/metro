from __future__ import annotations

from .plan import (
    AgentIntent,
    AgentPlan,
    AgentState,
    FacilityStage,
    PlanAction,
    PlanActionKind,
    RouteKey,
)
from ..station.graph import StationGraph


def plan_for_station_graph(
    intent: str | AgentIntent,
    station_graph: StationGraph,
) -> AgentPlan:
    intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
    vertical_transfers = station_graph.vertical_transfer_count_for_intent(intent_value)
    if intent_value == AgentIntent.EXIT_STATION.value:
        return _exit_station_plan(vertical_transfers)
    if intent_value == AgentIntent.TRANSFER.value:
        return _transfer_plan(vertical_transfers)
    return _enter_and_board_plan(vertical_transfers)


def _enter_and_board_plan(vertical_transfers: int) -> AgentPlan:
    facility_chain = (
        FacilityStage.ENTRY_GATE.value,
        *((FacilityStage.VERTICAL_TRANSFER.value,) * vertical_transfers),
        FacilityStage.BOARDING_DOOR.value,
    )
    actions: list[PlanAction] = [
        PlanAction(
            kind=PlanActionKind.CHOOSE_FACILITY.value,
            label="entry gate decision",
            trigger_state=AgentState.ENTERING_STATION.value,
            stage=FacilityStage.ENTRY_GATE.value,
            next_state=AgentState.CHOOSING_GATE.value,
        )
    ]
    if vertical_transfers:
        actions.append(
            PlanAction(
                kind=PlanActionKind.WALK_ROUTE.value,
                label="vertical transfer decision",
                trigger_state=AgentState.PASSING_GATE.value,
                route_key=RouteKey.AFTER_GATE.value,
                next_state=AgentState.WALKING_TO_VERTICAL.value,
                completed_stage=FacilityStage.ENTRY_GATE.value,
            )
        )
    else:
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_PLATFORM.value,
                label="platform waiting area",
                trigger_state=AgentState.PASSING_GATE.value,
                route_key=RouteKey.AFTER_VERTICAL.value,
                next_state=AgentState.WALKING_TO_PLATFORM.value,
                completed_stage=FacilityStage.ENTRY_GATE.value,
            )
        )

    for index in range(vertical_transfers):
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_FACILITY.value,
                label="vertical transfer decision",
                trigger_state=AgentState.WALKING_TO_VERTICAL.value,
                stage=FacilityStage.VERTICAL_TRANSFER.value,
                next_state=AgentState.CHOOSING_VERTICAL.value,
            )
        )
        is_last_vertical = index == vertical_transfers - 1
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_PLATFORM.value
                if is_last_vertical
                else PlanActionKind.WALK_ROUTE.value,
                label="platform waiting area"
                if is_last_vertical
                else "next vertical transfer decision",
                trigger_state=AgentState.RIDING_VERTICAL.value,
                route_key=RouteKey.AFTER_VERTICAL.value
                if is_last_vertical
                else RouteKey.AFTER_GATE.value,
                next_state=AgentState.WALKING_TO_PLATFORM.value
                if is_last_vertical
                else AgentState.WALKING_TO_VERTICAL.value,
                completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
            )
        )

    actions.extend(_platform_boarding_tail())
    return AgentPlan(
        intent=AgentIntent.ENTER_AND_BOARD.value,
        facility_chain=facility_chain,
        action_sequence=tuple(actions),
    )


def _exit_station_plan(vertical_transfers: int) -> AgentPlan:
    facility_chain = (
        *((FacilityStage.VERTICAL_TRANSFER.value,) * vertical_transfers),
        FacilityStage.EXIT_GATE.value,
    )
    actions: list[PlanAction] = []
    initial_state = AgentState.WALKING_TO_VERTICAL.value
    initial_route_key = RouteKey.PLATFORM_TO_VERTICAL.value
    initial_goal_label = "vertical transfer decision"
    if not vertical_transfers:
        initial_state = AgentState.WALKING_TO_EXIT_GATE.value
        initial_route_key = RouteKey.AFTER_EXIT_VERTICAL.value
        initial_goal_label = "exit gate decision"

    for index in range(vertical_transfers):
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_FACILITY.value,
                label="vertical transfer decision",
                trigger_state=AgentState.WALKING_TO_VERTICAL.value,
                stage=FacilityStage.VERTICAL_TRANSFER.value,
                next_state=AgentState.CHOOSING_VERTICAL.value,
            )
        )
        is_last_vertical = index == vertical_transfers - 1
        actions.append(
            PlanAction(
                kind=PlanActionKind.WALK_ROUTE.value,
                label="exit gate decision"
                if is_last_vertical
                else "next vertical transfer decision",
                trigger_state=AgentState.RIDING_VERTICAL.value,
                route_key=RouteKey.AFTER_EXIT_VERTICAL.value
                if is_last_vertical
                else RouteKey.PLATFORM_TO_VERTICAL.value,
                next_state=AgentState.WALKING_TO_EXIT_GATE.value
                if is_last_vertical
                else AgentState.WALKING_TO_VERTICAL.value,
                completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
            )
        )

    actions.extend(
        (
            PlanAction(
                kind=PlanActionKind.CHOOSE_FACILITY.value,
                label="exit gate decision",
                trigger_state=AgentState.WALKING_TO_EXIT_GATE.value,
                stage=FacilityStage.EXIT_GATE.value,
                next_state=AgentState.CHOOSING_EXIT_GATE.value,
            ),
            PlanAction(
                kind=PlanActionKind.DEPART.value,
                label="left station",
                trigger_state=AgentState.PASSING_EXIT_GATE.value,
                completed_stage=FacilityStage.EXIT_GATE.value,
            ),
        )
    )
    return AgentPlan(
        intent=AgentIntent.EXIT_STATION.value,
        facility_chain=facility_chain,
        initial_state=initial_state,
        initial_route_key=initial_route_key,
        initial_goal_label=initial_goal_label,
        action_sequence=tuple(actions),
    )


def _transfer_plan(vertical_transfers: int) -> AgentPlan:
    facility_chain = (
        *((FacilityStage.VERTICAL_TRANSFER.value,) * vertical_transfers),
        FacilityStage.BOARDING_DOOR.value,
    )
    if vertical_transfers <= 0:
        return AgentPlan(
            intent=AgentIntent.TRANSFER.value,
            facility_chain=facility_chain,
            initial_state=AgentState.WALKING_TO_TRANSFER.value,
            initial_route_key=RouteKey.CURRENT_POSITION.value,
            initial_goal_label="transfer platform decision",
            action_sequence=(
                PlanAction(
                    kind=PlanActionKind.CHOOSE_PLATFORM.value,
                    label="transfer platform waiting area",
                    trigger_state=AgentState.WALKING_TO_TRANSFER.value,
                    route_key=RouteKey.AFTER_VERTICAL.value,
                    next_state=AgentState.WALKING_TO_PLATFORM.value,
                ),
                *_platform_boarding_tail(),
            ),
        )

    actions: list[PlanAction] = []
    for index in range(vertical_transfers):
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_FACILITY.value,
                label="transfer vertical decision",
                trigger_state=AgentState.WALKING_TO_VERTICAL.value,
                stage=FacilityStage.VERTICAL_TRANSFER.value,
                next_state=AgentState.CHOOSING_VERTICAL.value,
            )
        )
        is_last_vertical = index == vertical_transfers - 1
        actions.append(
            PlanAction(
                kind=PlanActionKind.CHOOSE_PLATFORM.value
                if is_last_vertical
                else PlanActionKind.WALK_ROUTE.value,
                label="transfer platform waiting area"
                if is_last_vertical
                else "next transfer vertical decision",
                trigger_state=AgentState.RIDING_VERTICAL.value,
                route_key=RouteKey.AFTER_VERTICAL.value
                if is_last_vertical
                else RouteKey.PLATFORM_TO_VERTICAL.value,
                next_state=AgentState.WALKING_TO_PLATFORM.value
                if is_last_vertical
                else AgentState.WALKING_TO_VERTICAL.value,
                completed_stage=FacilityStage.VERTICAL_TRANSFER.value,
            )
        )
    actions.extend(_platform_boarding_tail())
    return AgentPlan(
        intent=AgentIntent.TRANSFER.value,
        facility_chain=facility_chain,
        initial_state=AgentState.WALKING_TO_VERTICAL.value,
        initial_route_key=RouteKey.PLATFORM_TO_VERTICAL.value,
        initial_goal_label="transfer vertical decision",
        action_sequence=tuple(actions),
    )


def _platform_boarding_tail() -> list[PlanAction]:
    return [
        PlanAction(
            kind=PlanActionKind.JOIN_PLATFORM.value,
            label="platform waiting area",
            trigger_state=AgentState.WALKING_TO_PLATFORM.value,
        ),
        PlanAction(
            kind=PlanActionKind.DEPART.value,
            label="boarded train",
            trigger_state=AgentState.BOARDING_TRAIN.value,
            completed_stage=FacilityStage.BOARDING_DOOR.value,
            counts_boarded=True,
        ),
    ]
