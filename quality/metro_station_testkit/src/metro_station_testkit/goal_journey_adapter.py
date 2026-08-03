"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import GoalEvent, GoalEventKind
from metro_station.adapters.simulation.planning.goal_graph import JourneyGraph
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from metro_station.adapters.simulation.planning.plan import FacilityStage
from .goal_journey_micro_scene import GoalJourneyMicroScene
from .goal_journey_observation import (
    distance,
    facility_disabled,
    facility_path_blocked,
    journey_decision_observation,
)
from .goal_journey_service_observer import GoalJourneyServiceObserver


class GoalJourneyObservationAdapter:
    def __init__(self) -> None:
        self._service = GoalJourneyServiceObserver()
        self._last_stall_emit_seconds = -1e9
        self._last_candidate_emit_seconds = -1e9

    def observe(
        self,
        context: GoalJourneyMicroScene,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        scene = context
        service = self._service.observe(scene, state)
        if service is not None:
            return service
        node = graph.node(state.current_node_id)
        if node.kind == "enter_region":
            return self._region_event(scene, str(node.region_id))
        if node.kind != "use_facility_stage":
            return None
        return self._facility_event(scene, state)

    def _region_event(self, scene: GoalJourneyMicroScene, region_id: str) -> GoalEvent | None:
        target = scene.region_positions[region_id]
        if distance(scene.subject.pos, target) > scene.region_radius:
            return None
        return GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=scene.current_time_seconds,
            region_id=region_id,
        )

    def _facility_event(
        self,
        scene: GoalJourneyMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        interaction = state.interaction_state
        if interaction == FacilityInteractionState.APPROACH_DECISION_REGION.value:
            node = state.current_node_id
            region_id = {
                "use_entry_gate": "entry_gate_decision",
                "use_vertical_transfer": "vertical_decision",
                "use_boarding_door": "boarding_decision",
            }[node]
            return self._region_event(scene, region_id)
        if interaction in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            return self._candidate_event(scene, str(state.current_stage))
        if state.commitment is None:
            return None
        facility = scene.facilities_by_id[state.commitment.facility_id]
        if facility_disabled(scene, facility.facility_id, str(state.current_stage)):
            return GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=facility.facility_id,
                reason="facility_disabled",
            )
        if interaction == FacilityInteractionState.APPROACH_QUEUE.value:
            return self._approach_event(scene, facility)
        if interaction == FacilityInteractionState.CAPTURE_QUEUE.value:
            if scene.subject in facility.queue:
                return GoalEvent(
                    kind=GoalEventKind.QUEUE_JOINED.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=facility.facility_id,
                )
            return None
        if interaction == FacilityInteractionState.QUEUEING.value:
            if self._boarding_blocked(scene, facility.facility_id, str(state.current_stage)):
                return self._stall_event(scene, "train_full_or_door_blocked")
        return None

    def _approach_event(self, scene: GoalJourneyMicroScene, facility) -> GoalEvent | None:
        if distance(scene.subject.pos, facility.spec.queue_anchor) <= scene.queue_capture_radius:
            return GoalEvent(
                kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=facility.facility_id,
            )
        if facility_path_blocked(scene, facility):
            return self._stall_event(scene, "people_blocking_facility")
        return None

    def _candidate_event(self, scene: GoalJourneyMicroScene, stage: str) -> GoalEvent | None:
        if scene.current_time_seconds <= self._last_candidate_emit_seconds + 1e-9:
            return None
        self._last_candidate_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=scene.current_time_seconds,
            observation=journey_decision_observation(scene, stage),
        )

    def _boarding_blocked(
        self,
        scene: GoalJourneyMicroScene,
        facility_id: str,
        stage: str,
    ) -> bool:
        if stage != FacilityStage.BOARDING_DOOR.value or not scene.train.is_boarding:
            return False
        return (
            scene.train.capacity_remaining < 1
            or facility_id in scene.service_blocked_door_ids
        )

    def _stall_event(self, scene: GoalJourneyMicroScene, reason: str) -> GoalEvent | None:
        if scene.current_time_seconds - self._last_stall_emit_seconds < 1.0:
            return None
        self._last_stall_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=scene.current_time_seconds,
            reason=reason,
        )
