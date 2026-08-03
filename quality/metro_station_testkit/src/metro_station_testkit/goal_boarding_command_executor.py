"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_commands import GoalCommand, GoalCommandKind
from metro_station.adapters.simulation.planning.goal_events import GoalEvent
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_boarding_micro_scene import GoalBoardingMicroScene


class GoalBoardingCommandExecutor:
    def execute(
        self,
        context: GoalBoardingMicroScene,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]:
        del current_stage
        scene = context
        for command in commands:
            self._execute_one(scene, command)
        return ()

    def _execute_one(self, scene: GoalBoardingMicroScene, command: GoalCommand) -> None:
        passenger = scene.subject
        if command.kind == GoalCommandKind.WALK_TO_REGION.value:
            passenger.state = AgentState.WALKING_TO_PLATFORM.value
            passenger.set_target(
                scene.decision_position,
                goal_kind="region",
                goal_label="boarding decision",
            )
            return
        if command.kind == GoalCommandKind.SELECT_FACILITY.value:
            passenger.assigned_facility_id = command.facility_id
            return
        if command.kind == GoalCommandKind.WALK_TO_QUEUE.value:
            door = scene.doors_by_id[str(command.facility_id)]
            passenger.state = AgentState.WALKING_TO_PLATFORM.value
            passenger.set_target(
                door.spec.queue_anchor,
                goal_kind="queue_capture",
                goal_label=f"{door.spec.label} queue capture",
                facility_id=door.facility_id,
                stage=door.spec.stage,
            )
            return
        if command.kind == GoalCommandKind.JOIN_QUEUE.value:
            scene.doors_by_id[str(command.facility_id)].join_queue(
                passenger,
                authority="goal_graph",
            )
            return
        if command.kind == GoalCommandKind.COMPLETE_JOURNEY.value:
            scene.complete_departure(passenger)
            return
        if command.kind == GoalCommandKind.REPLAN_STAGE.value:
            for door in scene.doors:
                door.queue.discard(passenger)
            passenger.assigned_facility_id = None
            passenger.state = AgentState.WALKING_TO_PLATFORM.value
            if passenger not in scene.passengers:
                scene.passengers.append(passenger)
            passenger.set_target(
                scene.decision_position,
                goal_kind="decision_region",
                goal_label="boarding decision",
            )
