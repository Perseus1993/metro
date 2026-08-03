"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_commands import GoalCommand, GoalCommandKind
from metro_station.adapters.simulation.planning.goal_events import GoalEvent
from metro_station.adapters.simulation.planning.plan import AgentState, FacilityStage
from .goal_journey_micro_scene import GoalJourneyMicroScene


STATE_BY_STAGE = {
    FacilityStage.ENTRY_GATE.value: AgentState.ENTERING_STATION.value,
    FacilityStage.VERTICAL_TRANSFER.value: AgentState.WALKING_TO_VERTICAL.value,
    FacilityStage.BOARDING_DOOR.value: AgentState.WALKING_TO_PLATFORM.value,
}


class GoalJourneyCommandExecutor:
    def execute(
        self,
        context: GoalJourneyMicroScene,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]:
        scene = context
        for command in commands:
            self._execute_one(scene, command, current_stage=current_stage)
        return ()

    def _execute_one(
        self,
        scene: GoalJourneyMicroScene,
        command: GoalCommand,
        *,
        current_stage: str | None,
    ) -> None:
        passenger = scene.subject
        if command.kind == GoalCommandKind.WALK_TO_REGION.value:
            self._move_to_region(scene, str(command.target_region_id))
            return
        if command.kind == GoalCommandKind.SELECT_FACILITY.value:
            passenger.assigned_facility_id = command.facility_id
            return
        if command.kind == GoalCommandKind.WALK_TO_QUEUE.value:
            facility = scene.facilities_by_id[str(command.facility_id)]
            passenger.state = STATE_BY_STAGE[facility.spec.stage]
            passenger.set_target(
                facility.spec.queue_anchor,
                goal_kind="queue_capture",
                goal_label=f"{facility.spec.label} queue capture",
                facility_id=facility.facility_id,
                stage=facility.spec.stage,
            )
            return
        if command.kind == GoalCommandKind.JOIN_QUEUE.value:
            scene.facilities_by_id[str(command.facility_id)].join_queue(
                passenger,
                authority="goal_graph",
            )
            return
        if command.kind == GoalCommandKind.COMPLETE_JOURNEY.value:
            scene.complete_departure(passenger)
            return
        if command.kind == GoalCommandKind.REPLAN_STAGE.value:
            self._reconsider(scene, str(current_stage))

    def _move_to_region(self, scene: GoalJourneyMicroScene, region_id: str) -> None:
        passenger = scene.subject
        passenger.state = (
            AgentState.WALKING_TO_PLATFORM.value
            if region_id in {"platform_landing", "boarding_decision"}
            else AgentState.WALKING_TO_VERTICAL.value
            if region_id == "vertical_decision"
            else AgentState.ENTERING_STATION.value
        )
        passenger.set_target(
            scene.region_positions[region_id],
            goal_kind="region",
            goal_label=region_id,
        )

    def _reconsider(self, scene: GoalJourneyMicroScene, stage: str) -> None:
        passenger = scene.subject
        for facility in scene.facilities:
            facility.queue.discard(passenger)
        passenger.assigned_facility_id = None
        passenger.state = STATE_BY_STAGE[stage]
        if passenger not in scene.passengers:
            scene.passengers.append(passenger)
        decision_region = {
            FacilityStage.ENTRY_GATE.value: "entry_gate_decision",
            FacilityStage.VERTICAL_TRANSFER.value: "vertical_decision",
            FacilityStage.BOARDING_DOOR.value: "boarding_decision",
        }[stage]
        passenger.set_target(
            scene.region_positions[decision_region],
            goal_kind="decision_region",
            goal_label=decision_region,
        )
