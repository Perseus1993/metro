"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from metro_station.adapters.simulation.planning.goal_events import (
    GoalEvent,
    GoalEventKind,
)
from metro_station.adapters.simulation.planning.goal_graph import JourneyGraph
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_stairs_micro_scene import GoalStairsMicroScene
from .goal_stairs_observation import (
    distance,
    platform_landing_blocked,
    stair_entrance_blocked,
    stairs_decision_observation,
)
from .goal_stairs_service_observer import GoalStairsServiceObserver


class GoalStairsObservationAdapter:
    """Convert stair positions, queues, service, and level changes into GoalEvents."""

    def __init__(self) -> None:
        self._service_observer = GoalStairsServiceObserver()
        self._last_stall_emit_seconds = -1e9
        self._last_candidate_emit_seconds = -1e9

    def observe(
        self,
        context: GoalStairsMicroScene,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        scene = context
        event = self._service_observer.observe(scene, state)
        if event is not None:
            return event
        node = graph.node(state.current_node_id)
        if node.kind == "enter_region":
            return self._region_event(scene, str(node.region_id))
        if node.kind != "use_facility_stage":
            return None
        return self._facility_event(scene, state)

    def _region_event(self, scene: GoalStairsMicroScene, region_id: str) -> GoalEvent | None:
        target, radius = {
            "vertical_decision": (scene.decision_position, scene.decision_radius),
            "platform_landing": (scene.platform_landing_position, scene.landing_radius),
        }[region_id]
        if distance(scene.subject.pos, target) <= radius:
            return GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=scene.current_time_seconds,
                region_id=region_id,
            )
        if region_id == "platform_landing" and platform_landing_blocked(scene):
            return self._stall_event(scene, "platform_landing_crowding")
        return None

    def _facility_event(
        self,
        scene: GoalStairsMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        interaction = state.interaction_state
        if interaction == FacilityInteractionState.APPROACH_DECISION_REGION.value:
            return self._decision_region_event(scene)
        if interaction in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            return self._candidate_event(scene)
        if state.commitment is None:
            return None
        stairs = scene.stairs_by_id[state.commitment.facility_id]
        if stairs.facility_id in scene.disabled_stair_ids:
            return GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=stairs.facility_id,
                reason="stairs_closed",
            )
        if interaction == FacilityInteractionState.APPROACH_QUEUE.value:
            if distance(scene.subject.pos, stairs.spec.queue_anchor) <= scene.queue_capture_radius:
                return GoalEvent(
                    kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=stairs.facility_id,
                )
            if stair_entrance_blocked(scene, stairs.facility_id):
                return self._stall_event(scene, "people_blocking_stairs_entrance")
        if interaction == FacilityInteractionState.CAPTURE_QUEUE.value:
            if scene.subject in stairs.queue:
                return GoalEvent(
                    kind=GoalEventKind.QUEUE_JOINED.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=stairs.facility_id,
                )
        return None

    def _decision_region_event(self, scene: GoalStairsMicroScene) -> GoalEvent | None:
        if distance(scene.subject.pos, scene.decision_position) > scene.decision_radius:
            return None
        return GoalEvent(
            kind=GoalEventKind.ENTERED_REGION.value,
            time_seconds=scene.current_time_seconds,
            region_id="vertical_decision",
        )

    def _candidate_event(self, scene: GoalStairsMicroScene) -> GoalEvent | None:
        if scene.current_time_seconds <= self._last_candidate_emit_seconds + 1e-9:
            return None
        self._last_candidate_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=scene.current_time_seconds,
            observation=stairs_decision_observation(scene),
        )

    def _stall_event(self, scene: GoalStairsMicroScene, reason: str) -> GoalEvent | None:
        if scene.current_time_seconds - self._last_stall_emit_seconds < 1.0:
            return None
        self._last_stall_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=scene.current_time_seconds,
            reason=reason,
        )
