"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from metro_station.adapters.simulation.planning.plan import FacilityStage
from .goal_journey_micro_scene import GoalJourneyMicroScene


class GoalJourneyScenarioEnvironment:
    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.actions: set[str] = set()
        self.blocked_at: float | None = None
        self.delayed_at: float | None = None

    def apply(self, scene: GoalJourneyMicroScene, state: AgentGoalState) -> None:
        stage = state.current_stage
        if self.scenario_id == "crowded_full_journey":
            if stage in {
                FacilityStage.ENTRY_GATE.value,
                FacilityStage.VERTICAL_TRANSFER.value,
                FacilityStage.BOARDING_DOOR.value,
            }:
                self._block_committed(scene, state, str(stage))
            return
        if self.scenario_id == "gate_replan":
            self._block_selected(scene, state, FacilityStage.ENTRY_GATE.value, "gate_1")
            return
        if self.scenario_id == "stairs_replan":
            self._block_selected(
                scene,
                state,
                FacilityStage.VERTICAL_TRANSFER.value,
                "stairs_1",
            )
            return
        if self.scenario_id == "door_replan":
            self._block_selected(scene, state, FacilityStage.BOARDING_DOOR.value, "door_1")
            return
        if stage != FacilityStage.BOARDING_DOOR.value:
            return
        if self.scenario_id == "delayed_train":
            self._delay_train(scene, state)
        elif self.scenario_id == "train_full_after_full_journey":
            self._fill_train(scene, state)

    def full_train_finished(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
    ) -> bool:
        return (
            self.scenario_id == "train_full_after_full_journey"
            and self.blocked_at is not None
            and scene.current_time_seconds >= self.blocked_at + 3.0
            and state.interaction_state == FacilityInteractionState.QUEUEING.value
            and state.commitment is not None
            and scene.train.capacity_remaining == 0
        )

    def _block_selected(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
        stage: str,
        facility_id: str,
    ) -> None:
        action = f"{facility_id}_blocked"
        if action in self.actions or state.current_stage != stage:
            return
        if state.commitment is None or state.commitment.facility_id != facility_id:
            return
        facility = scene.facilities_by_id[facility_id]
        scene.add_blocker_cluster(
            facility.spec.queue_anchor,
            level_id=str(facility.spec.entry_level_id),
        )
        self.actions.add(action)

    def _block_committed(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
        stage: str,
    ) -> None:
        action = f"crowded_{stage}_blocked"
        if action in self.actions or state.commitment is None:
            return
        facility = scene.facilities_by_id[state.commitment.facility_id]
        scene.add_blocker_cluster(
            facility.spec.queue_anchor,
            level_id=str(facility.spec.entry_level_id),
        )
        self.actions.add(action)

    def _delay_train(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.interaction_state != FacilityInteractionState.QUEUEING.value:
            return
        if "train_delayed" in self.actions:
            return
        scene.train.state = "away"
        scene.train.next_arrival_step = scene.step_index + 40
        scene.train.close_step = None
        self.delayed_at = scene.current_time_seconds
        self.actions.add("train_delayed")

    def _fill_train(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
    ) -> None:
        if state.interaction_state != FacilityInteractionState.QUEUEING.value:
            return
        if "train_filled" in self.actions:
            return
        scene.train.state = "boarding"
        scene.train.current_load_persons = scene.scenario.train_capacity_persons
        scene.train.close_step = scene.step_index + 10_000
        self.blocked_at = scene.current_time_seconds
        self.actions.add("train_filled")
