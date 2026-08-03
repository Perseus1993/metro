"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_boarding_micro_scene import GoalBoardingMicroScene


class GoalBoardingScenarioEnvironment:
    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.actions: set[str] = set()
        self.conflict_arrival_at: float | None = None
        self.terminal_wait_started_at: float | None = None

    def apply(self, scene: GoalBoardingMicroScene, state: AgentGoalState) -> None:
        if self.scenario_id == "door_front_crowded":
            self._add_door_crowd(scene, state)
            return
        if self.scenario_id == "alighting_conflict":
            self._manage_alighting_conflict(scene, state)
            return
        if self.scenario_id == "train_full":
            self._make_train_full(scene, state)
            return
        if self.scenario_id == "train_not_open":
            self._keep_train_away(scene, state)

    def blocked_scenario_finished(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> bool:
        if self.terminal_wait_started_at is None:
            return False
        if scene.current_time_seconds < self.terminal_wait_started_at + 3.0:
            return False
        if self.scenario_id == "train_full":
            return (
                state.interaction_state == FacilityInteractionState.QUEUEING.value
                and state.commitment is not None
                and scene.train.capacity_remaining == 0
            )
        return (
            self.scenario_id == "train_not_open"
            and state.interaction_state == FacilityInteractionState.QUEUEING.value
            and state.commitment is not None
        )

    def _add_door_crowd(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.commitment is None or state.commitment.facility_id != "door_1":
            return
        if "door_crowd_added" in self.actions:
            return
        scene.add_blocker_cluster(scene.doors_by_id["door_1"].spec.queue_anchor)
        self.actions.add("door_crowd_added")

    def _manage_alighting_conflict(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> None:
        if (
            state.interaction_state == FacilityInteractionState.QUEUEING.value
            and "alighters_added" not in self.actions
        ):
            for door in scene.doors:
                scene.add_blocker_cluster(door.spec.queue_anchor)
            scene.service_blocked_door_ids.update(scene.doors_by_id)
            self.actions.add("alighters_added")
        if "alighters_added" not in self.actions or not scene.train.is_boarding:
            return
        if self.conflict_arrival_at is None:
            self.conflict_arrival_at = scene.current_time_seconds
            return
        if scene.current_time_seconds < self.conflict_arrival_at + 3.0:
            return
        if "alighters_cleared" in self.actions:
            return
        scene.clear_blockers()
        scene.service_blocked_door_ids.clear()
        self.actions.add("alighters_cleared")

    def _make_train_full(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.interaction_state != FacilityInteractionState.QUEUEING.value:
            return
        if "train_filled" in self.actions:
            return
        scene.train.state = "boarding"
        scene.train.current_load_persons = scene.scenario.train_capacity_persons
        # Keep the same observed train full for the complete blocked-scenario
        # window.  Allowing it to depart here turns the probe into a later,
        # empty-train boarding test instead of a capacity guard test.
        scene.train.close_step = scene.step_index + 10_000
        self.actions.add("train_filled")
        self.terminal_wait_started_at = scene.current_time_seconds

    def _keep_train_away(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.interaction_state != FacilityInteractionState.QUEUEING.value:
            return
        if "train_held_away" in self.actions:
            return
        scene.train.state = "away"
        scene.train.next_arrival_step = scene.step_index + 1000
        scene.train.close_step = None
        self.actions.add("train_held_away")
        self.terminal_wait_started_at = scene.current_time_seconds
