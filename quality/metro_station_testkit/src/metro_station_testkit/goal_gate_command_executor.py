"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_commands import GoalCommand, GoalCommandKind
from metro_station.adapters.simulation.planning.goal_events import GoalEvent
from metro_station.adapters.simulation.planning.plan import AgentState
from .goal_gate_micro_scene import GoalGateMicroScene


class GoalGateCommandExecutor:
    """Translate pure GoalCommands into micro-scene movement and queue operations."""

    def execute(
        self,
        context: GoalGateMicroScene,
        commands: tuple[GoalCommand, ...],
        *,
        current_stage: str | None = None,
    ) -> tuple[GoalEvent, ...]:
        del current_stage
        scene = context
        for command in commands:
            self._execute_one(scene, command)
        return ()

    def _execute_one(self, scene: GoalGateMicroScene, command: GoalCommand) -> None:
        passenger = scene.subject
        if command.kind == GoalCommandKind.WALK_TO_REGION.value:
            target = {
                "entry_gate_decision": scene.decision_position,
                "paid_hall": scene.paid_hall_position,
            }[str(command.target_region_id)]
            passenger.state = AgentState.ENTERING_STATION.value
            passenger.set_target(target, goal_kind="region", goal_label=str(command.target_region_id))
            return
        if command.kind == GoalCommandKind.SELECT_FACILITY.value:
            passenger.assigned_facility_id = command.facility_id
            return
        if command.kind == GoalCommandKind.WALK_TO_QUEUE.value:
            gate = scene.gates_by_id[str(command.facility_id)]
            passenger.state = AgentState.ENTERING_STATION.value
            passenger.set_target(
                gate.spec.queue_anchor,
                goal_kind="queue_capture",
                goal_label=f"{gate.spec.label} queue capture",
                facility_id=gate.facility_id,
                stage=gate.spec.stage,
            )
            return
        if command.kind == GoalCommandKind.JOIN_QUEUE.value:
            scene.gates_by_id[str(command.facility_id)].join_queue(
                passenger,
                authority="goal_graph",
            )
            return
        if command.kind == GoalCommandKind.REPLAN_STAGE.value:
            for gate in scene.gates:
                gate.queue.discard(passenger)
            passenger.assigned_facility_id = None
            passenger.state = AgentState.ENTERING_STATION.value
            passenger.set_target(
                scene.decision_position,
                goal_kind="decision_region",
                goal_label="entry gate decision",
            )
