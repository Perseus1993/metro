"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_stairs_fixture import CONCOURSE_LEVEL, PLATFORM_LEVEL
from .goal_stairs_micro_scene import GoalStairsMicroScene


class GoalStairsScenarioEnvironment:
    """Own scenario disturbances without coupling them to the probe lifecycle."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.actions: set[str] = set()
        self.exit_crowd_start: float | None = None
        self.disabled_at: float | None = None

    def apply(self, scene: GoalStairsMicroScene, state: AgentGoalState) -> None:
        if self.scenario_id == "entrance_crowded":
            self._add_entrance_crowd(scene, state)
            return
        if self.scenario_id == "exit_crowded":
            self._manage_exit_crowd(scene, state)
            return
        if self.scenario_id == "stairs_unavailable":
            self._disable_stairs(scene, state)

    def unavailable_wait_finished(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> bool:
        return (
            self.scenario_id == "stairs_unavailable"
            and self.disabled_at is not None
            and scene.current_time_seconds >= self.disabled_at + 3.0
            and state.interaction_state == FacilityInteractionState.EVALUATE_CANDIDATES.value
            and state.commitment is None
        )

    def _add_entrance_crowd(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.commitment is None or state.commitment.facility_id != "stairs_1":
            return
        if "entrance_crowd_added" in self.actions:
            return
        stairs = scene.stairs_by_id["stairs_1"]
        scene.add_blocker_cluster(
            stairs.spec.queue_anchor,
            level_id=CONCOURSE_LEVEL,
        )
        self.actions.add("entrance_crowd_added")

    def _manage_exit_crowd(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.current_node_id != "enter_platform_landing":
            return
        if "exit_crowd_added" not in self.actions:
            scene.add_blocker_cluster(
                scene.platform_landing_position,
                level_id=PLATFORM_LEVEL,
                rows=3,
                columns=5,
            )
            self.actions.add("exit_crowd_added")
            self.exit_crowd_start = scene.current_time_seconds
            return
        if self.exit_crowd_start is None or "exit_crowd_cleared" in self.actions:
            return
        if scene.current_time_seconds < self.exit_crowd_start + 3.0:
            return
        scene.clear_blockers()
        self.actions.add("exit_crowd_cleared")

    def _disable_stairs(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.commitment is None or "stairs_disabled" in self.actions:
            return
        scene.disabled_stair_ids.update(scene.stairs_by_id)
        self.actions.add("stairs_disabled")
        self.disabled_at = scene.current_time_seconds
