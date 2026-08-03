"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_commands import GoalCommand, GoalCommandKind
from metro_station.adapters.simulation.planning.goal_events import GoalEvent
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_stairs_micro_scene import GoalStairsMicroScene


class GoalStairsCommandExecutor:
    """Translate GoalCommands into stair approach, queue, and landing actions."""

    def execute(
        self,
        context: GoalStairsMicroScene,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]:
        del current_stage
        scene = context
        for command in commands:
            self._execute_one(scene, command)
        return ()

    def _execute_one(self, scene: GoalStairsMicroScene, command: GoalCommand) -> None:
        passenger = scene.subject
        if command.kind == GoalCommandKind.WALK_TO_REGION.value:
            target = {
                "vertical_decision": scene.decision_position,
                "platform_landing": scene.platform_landing_position,
            }[str(command.target_region_id)]
            passenger.state = (
                AgentState.WALKING_TO_VERTICAL.value
                if command.target_region_id == "vertical_decision"
                else AgentState.WALKING_TO_PLATFORM.value
            )
            passenger.set_target(
                target,
                goal_kind="region",
                goal_label=str(command.target_region_id),
            )
            return
        if command.kind == GoalCommandKind.SELECT_FACILITY.value:
            passenger.assigned_facility_id = command.facility_id
            return
        if command.kind == GoalCommandKind.WALK_TO_QUEUE.value:
            stairs = scene.stairs_by_id[str(command.facility_id)]
            passenger.state = AgentState.WALKING_TO_VERTICAL.value
            passenger.set_target(
                stairs.spec.queue_anchor,
                goal_kind="queue_capture",
                goal_label=f"{stairs.spec.label} queue capture",
                facility_id=stairs.facility_id,
                stage=stairs.spec.stage,
            )
            return
        if command.kind == GoalCommandKind.JOIN_QUEUE.value:
            scene.stairs_by_id[str(command.facility_id)].join_queue(
                passenger,
                authority="goal_graph",
            )
            return
        if command.kind == GoalCommandKind.REPLAN_STAGE.value:
            for stairs in scene.stairs:
                stairs.queue.discard(passenger)
            passenger.assigned_facility_id = None
            passenger.state = AgentState.WALKING_TO_VERTICAL.value
            passenger.set_target(
                scene.decision_position,
                goal_kind="decision_region",
                goal_label="vertical transfer decision",
            )
