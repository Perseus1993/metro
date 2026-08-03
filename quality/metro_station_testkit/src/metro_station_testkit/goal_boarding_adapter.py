"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_graph import JourneyGraph
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_boarding_micro_scene import GoalBoardingMicroScene
from .goal_boarding_observation import (
    boarding_decision_observation,
    distance,
    door_front_blocked,
)
from .goal_boarding_service_observer import GoalBoardingServiceObserver


class GoalBoardingObservationAdapter:
    def __init__(self) -> None:
        self._service_observer = GoalBoardingServiceObserver()
        self._last_stall_emit_seconds = -1e9
        self._last_candidate_emit_seconds = -1e9

    def observe(
        self,
        context: GoalBoardingMicroScene,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        scene = context
        service = self._service_observer.observe(scene, state)
        if service is not None:
            return service
        node = graph.node(state.current_node_id)
        if node.kind == "enter_region":
            return self._region_event(scene, str(node.region_id))
        if node.kind != "use_facility_stage":
            return None
        return self._facility_event(scene, state)

    def _region_event(
        self,
        scene: GoalBoardingMicroScene,
        region_id: str,
    ) -> GoalEvent | None:
        if region_id != "boarding_decision":
            return None
        if distance(scene.subject.pos, scene.decision_position) > scene.decision_radius:
            return None
        return GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=scene.current_time_seconds,
            region_id=region_id,
        )

    def _facility_event(
        self,
        scene: GoalBoardingMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        interaction = state.interaction_state
        if interaction == FacilityInteractionState.APPROACH_DECISION_REGION.value:
            return self._region_event(scene, "boarding_decision")
        if interaction in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            return self._candidate_event(scene)
        if state.commitment is None:
            return None
        door = scene.doors_by_id[state.commitment.facility_id]
        if door.facility_id in scene.disabled_door_ids:
            return GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=door.facility_id,
                reason="boarding_door_disabled",
            )
        if interaction == FacilityInteractionState.APPROACH_QUEUE.value:
            return self._approach_event(scene, door.facility_id)
        if interaction == FacilityInteractionState.CAPTURE_QUEUE.value:
            if scene.subject in door.queue:
                return GoalEvent(
                    kind=GoalEventKind.QUEUE_JOINED.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=door.facility_id,
                )
            return None
        if interaction == FacilityInteractionState.QUEUEING.value:
            if scene.train.is_boarding and scene.train.capacity_remaining < 1:
                return self._stall_event(scene, "train_full")
            if (
                scene.train.is_boarding
                and door.facility_id in scene.service_blocked_door_ids
            ):
                return self._stall_event(scene, "alighting_conflict")
        return None

    def _approach_event(
        self,
        scene: GoalBoardingMicroScene,
        facility_id: str,
    ) -> GoalEvent | None:
        door = scene.doors_by_id[facility_id]
        if distance(scene.subject.pos, door.spec.queue_anchor) <= scene.queue_capture_radius:
            return GoalEvent(
                kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=facility_id,
            )
        if door_front_blocked(scene, facility_id):
            return self._stall_event(scene, "people_blocking_boarding_door")
        return None

    def _candidate_event(self, scene: GoalBoardingMicroScene) -> GoalEvent | None:
        if scene.current_time_seconds <= self._last_candidate_emit_seconds + 1e-9:
            return None
        self._last_candidate_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=scene.current_time_seconds,
            observation=boarding_decision_observation(scene),
        )

    def _stall_event(self, scene: GoalBoardingMicroScene, reason: str) -> GoalEvent | None:
        if scene.current_time_seconds - self._last_stall_emit_seconds < 1.0:
            return None
        self._last_stall_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=scene.current_time_seconds,
            reason=reason,
        )
