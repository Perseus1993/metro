"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from math import hypot, pi

from metro_station.adapters.simulation.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from metro_station.adapters.simulation.planning.goal_graph import JourneyGraph
from metro_station.adapters.simulation.planning.goal_state import AgentGoalState, FacilityInteractionState
from .goal_gate_micro_scene import GoalGateMicroScene
from .goal_gate_service_observer import GoalGateServiceObserver


class GoalGateObservationAdapter:
    """Convert physical positions, crowding, queues, and gate events into GoalEvents."""

    def __init__(self) -> None:
        self._service_observer = GoalGateServiceObserver()
        self._last_stall_emit_seconds = -1e9
        self._last_candidate_emit_seconds = -1e9

    def observe(
        self,
        context: GoalGateMicroScene,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        scene = context
        event = self._service_observer.observe(scene, state)
        if event is not None:
            return event
        node = graph.node(state.current_node_id)
        if node.kind == "enter_region":
            return self._region_event(scene, state, str(node.region_id))
        if node.kind != "use_facility_stage":
            return None
        return self._facility_event(scene, state)

    def _region_event(
        self,
        scene: GoalGateMicroScene,
        state: AgentGoalState,
        region_id: str,
    ) -> GoalEvent | None:
        target, radius = {
            "entry_gate_decision": (scene.decision_position, scene.decision_radius),
            "paid_hall": (scene.paid_hall_position, scene.paid_hall_radius),
        }[region_id]
        if _distance(scene.subject.pos, target) <= radius:
            return GoalEvent(
                kind=GoalEventKind.ENTERED_REGION.value,
                time_seconds=scene.current_time_seconds,
                region_id=region_id,
            )
        if region_id == "paid_hall" and scene.blocker_count_near(target, 1.5) >= 4:
            return self._stall_event(scene, state, "paid_hall_crowding")
        return None

    def _facility_event(
        self,
        scene: GoalGateMicroScene,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        interaction = state.interaction_state
        if interaction == FacilityInteractionState.APPROACH_DECISION_REGION.value:
            if _distance(scene.subject.pos, scene.decision_position) <= scene.decision_radius:
                return GoalEvent(
                    kind=GoalEventKind.ENTERED_REGION.value,
                    time_seconds=scene.current_time_seconds,
                    region_id="entry_gate_decision",
                )
            return None
        if interaction in {
            FacilityInteractionState.EVALUATE_CANDIDATES.value,
            FacilityInteractionState.REPLAN_PENDING.value,
        }:
            if scene.current_time_seconds <= self._last_candidate_emit_seconds + 1e-9:
                return None
            self._last_candidate_emit_seconds = scene.current_time_seconds
            return GoalEvent(
                kind=GoalEventKind.CANDIDATES_UPDATED.value,
                time_seconds=scene.current_time_seconds,
                observation=self._observation(scene),
            )
        if state.commitment is None:
            return None
        gate = scene.gates_by_id[state.commitment.facility_id]
        if gate.facility_id in scene.disabled_gate_ids:
            return GoalEvent(
                kind=GoalEventKind.FACILITY_UNAVAILABLE.value,
                time_seconds=scene.current_time_seconds,
                facility_id=gate.facility_id,
                reason="gate_closed",
            )
        if interaction == FacilityInteractionState.APPROACH_QUEUE.value:
            if _distance(scene.subject.pos, gate.spec.queue_anchor) <= scene.queue_capture_radius:
                return GoalEvent(
                    kind=GoalEventKind.REACHED_QUEUE_CAPTURE.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=gate.facility_id,
                )
            if self._gate_path_blocked(scene, gate.facility_id):
                return self._stall_event(scene, state, "people_blocking_gate")
        if interaction == FacilityInteractionState.CAPTURE_QUEUE.value:
            if scene.subject in gate.queue:
                return GoalEvent(
                    kind=GoalEventKind.QUEUE_JOINED.value,
                    time_seconds=scene.current_time_seconds,
                    facility_id=gate.facility_id,
                )
        return None

    def _observation(self, scene: GoalGateMicroScene) -> DecisionObservation:
        facilities = []
        for gate in scene.gates:
            blocker_count = scene.blocker_count_near(gate.spec.queue_anchor, 1.2)
            facilities.append(
                FacilityObservation(
                    facility_id=gate.facility_id,
                    stage=gate.spec.stage,
                    available=gate.facility_id not in scene.disabled_gate_ids,
                    reachable=blocker_count < 4,
                    walking_time_seconds=_distance(scene.subject.pos, gate.spec.queue_anchor) / 1.2,
                    queue_persons=gate.queue_persons,
                    estimated_wait_seconds=gate.queue_persons
                    / max(0.001, gate.effective_service_persons_per_min)
                    * 60,
                    local_density_persons_m2=blocker_count / (pi * 1.2**2),
                    service_state=gate.state,
                )
            )
        return DecisionObservation(
            time_seconds=scene.current_time_seconds,
            current_region_id="entry_gate_decision",
            candidates=tuple(facilities),
        )

    def _gate_path_blocked(self, scene: GoalGateMicroScene, facility_id: str) -> bool:
        gate = scene.gates_by_id[facility_id]
        return (
            scene.blocker_count_near(gate.spec.queue_anchor, 1.2) >= 4
            and _distance(scene.subject.pos, gate.spec.queue_anchor) <= 4.5
        )

    def _stall_event(
        self,
        scene: GoalGateMicroScene,
        state: AgentGoalState,
        reason: str,
    ) -> GoalEvent | None:
        del state
        if scene.current_time_seconds - self._last_stall_emit_seconds < 1.0:
            return None
        self._last_stall_emit_seconds = scene.current_time_seconds
        return GoalEvent(
            kind=GoalEventKind.PROGRESS_STALLED.value,
            time_seconds=scene.current_time_seconds,
            reason=reason,
        )


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])
