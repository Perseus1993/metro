from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import hypot, pi
from typing import TYPE_CHECKING, Any, cast

from ..facilities.filters import filter_facilities_for_passenger
from ..facilities.process import FacilityKind
from ..planning.goal_commands import GoalCommand, GoalCommandKind
from ..planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
    GoalEvent,
    GoalEventKind,
)
from ..planning.goal_graph import JourneyGraph
from ..planning.goal_state import AgentGoalState
from ..planning.plan import AgentIntent, FacilityStage
from .evacuation_journey_rerouting import refresh_evacuation_facility_path

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..facilities.runtime import FacilityProcessAgent
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class ProductionGoalObservationContext:
    model: MetroStationModel
    passenger: PassengerAgent
    command: GoalCommand


class ProductionGoalObservationAdapter:
    """Read production runtime facts and emit canonical GoalEvents."""

    def __init__(self, *, region_router=None) -> None:
        self.region_router = region_router

    def observe(
        self,
        context: ProductionGoalObservationContext,
        graph: JourneyGraph,
        state: AgentGoalState,
    ) -> GoalEvent | None:
        del graph
        command = context.command
        if GoalCommandKind(command.kind) != GoalCommandKind.OBSERVE_CANDIDATES:
            return None
        stage = command.stage or state.current_stage
        if stage is None:
            return None
        if (
            stage == FacilityStage.VERTICAL_TRANSFER.value
            and context.passenger.intent == AgentIntent.EVACUATE_STATION.value
            and state.commitment is None
            and state.queued_facility_id is None
            and not context.model.passenger_has_active_facility_service(
                context.passenger
            )
        ):
            refresh_evacuation_facility_path(
                context.model,
                context.passenger,
            )
        candidates = context.model._facilities_for_stage(stage)
        context_invalidated = False
        if self.region_router is not None and command.target_region_id is not None:
            context_invalidated = self.region_router.decision_context_needs_reroute(
                context.model,
                context.passenger,
                command.target_region_id,
                candidates,
            )
            if context_invalidated:
                self.region_router.clear_decision_context(
                    context.passenger,
                    command.target_region_id,
                )
                candidates = []
            else:
                candidates = list(
                    self.region_router.local_decision_facilities(
                        context.model,
                        context.passenger,
                        command.target_region_id,
                        candidates,
                    )
                )
        observations = build_goal_facility_observations(
            context.model,
            context.passenger,
            stage,
            candidates,
            goal_node_id=state.current_node_id,
        )
        event_time = max(
            context.model.current_time_seconds,
            state.last_event_time_seconds,
        )
        return GoalEvent(
            kind=GoalEventKind.CANDIDATES_UPDATED.value,
            time_seconds=event_time,
            event_id=_command_event_id(command, "candidates"),
            command_id=command.command_id,
            goal_node_id=command.goal_node_id,
            stage=stage,
            observation=DecisionObservation(
                time_seconds=event_time,
                current_region_id=command.target_region_id,
                entered_region_ids=(command.target_region_id,)
                if command.target_region_id is not None
                else (),
                candidates=observations,
                committed_facility_id=(
                    None if state.commitment is None else state.commitment.facility_id
                ),
                committed_at_seconds=(
                    None if state.commitment is None else state.commitment.committed_at_seconds
                ),
                reconsider_after_seconds=(
                    None if state.commitment is None else state.commitment.reconsider_after_seconds
                ),
                replan_reason=(
                    "decision_context_invalidated"
                    if context_invalidated
                    else state.replan_reason
                ),
                commitment_duration_seconds=float(
                    getattr(context.model.scenario, "facility_commitment_seconds", 15.0)
                ),
                replan_cooldown_seconds=float(
                    getattr(context.model.scenario, "facility_replan_cooldown_seconds", 30.0)
                ),
                minimum_improvement_seconds=float(
                    getattr(
                        context.model.scenario,
                        "facility_replan_minimum_improvement_seconds",
                        5.0,
                    )
                ),
            ),
        )


def build_goal_facility_observations(
    model: MetroStationModel,
    passenger: PassengerAgent,
    stage: str,
    candidates: list[FacilityProcessAgent],
    *,
    goal_node_id: str,
) -> tuple[FacilityObservation, ...]:
    reachable = set(
        filter_facilities_for_passenger(passenger, stage, cast(Any, candidates))
    )
    avoided = passenger.avoided_facility_ids_by_goal.get(goal_node_id, set())
    return tuple(
        _facility_observation(
            model,
            passenger,
            stage,
            facility,
            reachable=facility in reachable,
            avoided=facility.facility_id in avoided,
        )
        for facility in candidates
    )


def _facility_observation(
    model: MetroStationModel,
    passenger: PassengerAgent,
    stage: str,
    facility: FacilityProcessAgent,
    *,
    reachable: bool,
    avoided: bool,
) -> FacilityObservation:
    walking_distance, route_reachable, walking_cost_source = _walking_distance(
        model,
        passenger,
        facility,
    )
    walking_speed = float(model.desired_walk_speed_mps(passenger))
    walking_seconds = walking_distance / max(0.001, walking_speed)
    preference_penalty = _preference_penalty_seconds(model, passenger, stage, facility)
    guidance_adjustment = cast(Any, model).control_timeline_controller.guidance_cost_adjustment(
        passenger,
        facility,
    )
    avoidance_penalty = (
        float(model.scenario.replan_avoided_facility_penalty) if avoided else 0.0
    )
    queue_persons = _queue_persons_ahead(model, passenger, facility)
    wait_seconds = queue_persons / max(
        0.001,
        facility.effective_service_persons_per_min,
    ) * 60.0
    service_seconds = passenger.group_size / max(
        0.001,
        facility.effective_service_persons_per_min,
    ) * 60.0
    traversal_seconds = getattr(facility, "routing_traversal_seconds", None)
    if traversal_seconds is not None:
        service_seconds = max(service_seconds, max(0.0, float(traversal_seconds)))
    return FacilityObservation(
        facility_id=facility.facility_id,
        stage=stage,
        available=(
            facility.is_available_for_choice
            and model.facility_has_reservable_approach_slot(passenger, facility)
        ),
        reachable=reachable and route_reachable,
        walking_time_seconds=walking_seconds,
        queue_persons=queue_persons,
        estimated_wait_seconds=wait_seconds,
        local_density_persons_m2=_density_near_facility(model, facility),
        service_state=str(facility.state),
        service_time_seconds=service_seconds,
        walking_distance_units=walking_distance,
        walking_cost_source=walking_cost_source,
        preference_penalty_seconds=preference_penalty,
        guidance_adjustment_seconds=guidance_adjustment,
        avoidance_penalty_seconds=avoidance_penalty,
    )


def _walking_distance(
    model: MetroStationModel,
    passenger: PassengerAgent,
    facility: FacilityProcessAgent,
) -> tuple[float, bool, str]:
    route_provider = getattr(cast(Any, model), "facility_walking_route", None)
    if not callable(route_provider):
        route_provider = getattr(cast(Any, model), "route_to_facility_queue", None)
    if not callable(route_provider):
        return _direct_distance(passenger, facility), True, "euclidean_fallback"
    try:
        route = tuple(
            cast(Iterable[tuple[float, float]], route_provider(passenger, facility))
        )
    except (RuntimeError, ValueError):
        return _direct_distance(passenger, facility), False, "physical_route_unreachable"

    points = (tuple(passenger.pos), *route)
    if len(points) == 1:
        target_provider = getattr(
            cast(Any, model),
            "_safe_facility_queue_approach_target",
            None,
        )
        target = (
            cast(tuple[float, float], target_provider(passenger, facility))
            if callable(target_provider)
            else facility.spec.queue_anchor
        )
        points = (*points, tuple(target))
    distance = sum(
        hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(points, points[1:])
    )
    return distance, True, "physical_waypoint_geodesic"


def _direct_distance(passenger: PassengerAgent, facility: FacilityProcessAgent) -> float:
    px, py = passenger.pos
    qx, qy = facility.spec.queue_anchor
    return hypot(px - qx, py - qy)


def _queue_persons_ahead(
    model: MetroStationModel,
    passenger: PassengerAgent,
    facility: FacilityProcessAgent,
) -> int:
    queued = int(facility.queue_persons)
    if passenger in facility.queue:
        queued = max(0, queued - int(passenger.group_size))
    targeting = int(model.facility_targeting_persons(facility))
    if passenger.assigned_facility_id == facility.facility_id:
        targeting = max(0, targeting - int(passenger.group_size))
    return queued + targeting


def _preference_penalty_seconds(
    model: MetroStationModel,
    passenger: PassengerAgent,
    stage: str,
    facility: FacilityProcessAgent,
) -> float:
    if stage != FacilityStage.VERTICAL_TRANSFER.value:
        return 0.0
    if passenger.prefers_elevator and facility.spec.kind != FacilityKind.ELEVATOR.value:
        return float(model.scenario.elevator_preference_mismatch_penalty_seconds)
    if passenger.prefers_stairs and facility.spec.kind != FacilityKind.STAIRS.value:
        return float(model.scenario.stairs_preference_mismatch_penalty_seconds)
    if not passenger.prefers_elevator and facility.spec.kind == FacilityKind.ELEVATOR.value:
        return float(model.scenario.nonpreferred_elevator_penalty_seconds)
    if facility.spec.kind == FacilityKind.STAIRS.value:
        return float(getattr(facility, "fatigue_cost", 0.0)) * 60.0
    return 0.0


def _density_near_facility(
    model: MetroStationModel,
    facility: FacilityProcessAgent,
) -> float:
    radius = max(0.1, float(model.scenario.crowd_radius_units))
    qx, qy = facility.spec.queue_anchor
    persons = sum(
        passenger.group_size
        for passenger in model.active_passengers()
        if passenger.current_level_id == facility.spec.entry_level_id
        and hypot(passenger.pos[0] - qx, passenger.pos[1] - qy) <= radius
    )
    return persons / (pi * radius * radius)


def _command_event_id(command: GoalCommand, suffix: str) -> str | None:
    if command.command_id is None:
        return None
    return f"{command.command_id}:{suffix}"
