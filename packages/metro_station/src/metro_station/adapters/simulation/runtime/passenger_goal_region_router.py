from __future__ import annotations

from math import hypot

from shapely.geometry import Point as ShapelyPoint

from ..facilities.filters import filter_facilities_for_passenger
from ..planning.goal_choice import MinimumPerceivedCostSelector
from ..planning.goal_events import DecisionObservation
from ..planning.plan import AgentIntent, AgentState, FacilityStage
from ..station.geometry import project_to_safe_point
from .decision_holding import DecisionHoldingCapacityError, PlatformWaitingCapacityError
from .evacuation_journey_rerouting import refresh_evacuation_facility_path
from .passenger_goal_decision_geometry import PassengerGoalDecisionGeometryMixin
from .passenger_goal_observation import build_goal_facility_observations
from .service_chain_counters import (
    WAITING_CAPACITY_RETRY,
    increment_service_chain_counter,
)

_DECISION_REGION_STAGES = {
    "entry_gate_decision": FacilityStage.ENTRY_GATE.value,
    "vertical_decision": FacilityStage.VERTICAL_TRANSFER.value,
    "boarding_decision": FacilityStage.BOARDING_DOOR.value,
    "exit_gate_decision": FacilityStage.EXIT_GATE.value,
}
_MEMBERSHIP_REGION_STAGES = {
    "paid_hall",
    "platform_landing",
    "vertical_landing",
    "exit_hall",
}


class PassengerGoalRegionRouter(PassengerGoalDecisionGeometryMixin):
    """Translate strategic region ids into existing physical station routes."""

    def route(self, model, passenger, region_id: str) -> tuple[tuple[float, float], ...]:
        passenger.route_waypoint_radius_override = None
        region = self._base_region(region_id)
        self._apply_target_platform_constraints(model, passenger)
        if region in _DECISION_REGION_STAGES:
            stage = _DECISION_REGION_STAGES[region]
            target = self._decision_region_target(
                model,
                passenger,
                region,
                stage,
            )
            preferred_facility_id = passenger.decision_preferred_facility_id_by_region.get(region)
            preferred_facility = model.facilities_by_id.get(preferred_facility_id)
            if region in {"exit_gate_decision", "boarding_decision"}:
                if preferred_facility is not None:
                    # Crossing flows must follow the authored paid-side
                    # access topology. A direct, navigation-mesh-valid line
                    # either from a train to an exit gate or from an entry
                    # gate to a remote boarding target can cut across a fully
                    # occupied opposing FIFO because dynamic bodies are not
                    # static JuPedSim obstacles. Preserve tactical Station
                    # Graph anchors so both directions use certified aisles.
                    route = model._station_graph_route_to_facility(
                        passenger,
                        preferred_facility,
                        final_target_override=target,
                        include_navigation_waypoints=True,
                        preserve_gate_tactical_anchors=(region == "exit_gate_decision"),
                    )
                    if route:
                        return route
            return self._physical_region_route(model, passenger, target)
        if region in _MEMBERSHIP_REGION_STAGES:
            target = self._membership_region_target(model, passenger, region)
            return self._physical_region_route(model, passenger, target)
        if region in {"station_exit", "safe_zone", "station_exterior_safe_zone"}:
            if getattr(model.layout_graph, "station_graph", None) is not None:
                return model._station_graph_route_to_exit(passenger)
            target = self._nearest_exit(model, passenger.pos)
            return model._physical_route_for_points(passenger, (target,))
        raise ValueError(f"Goal Graph references unsupported region {region_id!r}")

    def reached(self, passenger, route: tuple[tuple[float, float], ...]) -> bool:
        if not route:
            return True
        target = route[-1]
        radius = float(passenger.model.scenario.jupedsim_target_radius_units)
        waypoint_override = getattr(
            passenger,
            "route_waypoint_radius_override",
            None,
        )
        if waypoint_override is not None:
            # The physical backend and Goal Region reducer must agree on the
            # final tactical boundary. Gate approaches deliberately use the
            # personal-space capture radius; retaining the default semantic
            # radius after JuPedSim has stopped at that boundary leaves a
            # permanently walking passenger just outside the reducer's view.
            radius = max(radius, float(waypoint_override))
        return hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1]) <= radius

    def walking_state(
        self,
        *,
        region_id: str | None = None,
        stage: str | None = None,
    ) -> str:
        region_id = None if region_id is None else self._base_region(region_id)
        if stage == FacilityStage.ENTRY_GATE.value or region_id == "entry_gate_decision":
            return AgentState.ENTERING_STATION.value
        if stage == FacilityStage.VERTICAL_TRANSFER.value or region_id in {
            "paid_hall",
            "vertical_decision",
        }:
            return AgentState.WALKING_TO_VERTICAL.value
        if stage == FacilityStage.EXIT_GATE.value or region_id in {
            "exit_hall",
            "exit_gate_decision",
            "station_exit",
            "safe_zone",
            "station_exterior_safe_zone",
        }:
            return AgentState.WALKING_TO_EXIT_GATE.value
        return AgentState.WALKING_TO_PLATFORM.value

    def _nearest_exit(self, model, position: tuple[float, float]) -> tuple[float, float]:
        entrances = tuple(model.layout_graph.geometry.entrances)
        if not entrances:
            return model.clamp_position(position)
        return model.clamp_position(min(entrances, key=lambda item: self._distance(position, item)))

    def _decision_region_target(
        self,
        model,
        passenger,
        region_id: str,
        stage: str,
    ) -> tuple[float, float]:
        if (
            stage == FacilityStage.VERTICAL_TRANSFER.value
            and passenger.intent == AgentIntent.EVACUATE_STATION.value
        ):
            refresh_evacuation_facility_path(model, passenger)
        candidates = filter_facilities_for_passenger(
            passenger,
            stage,
            model._facilities_for_stage(stage),
        )
        level_id = passenger.current_level_id
        candidates = [
            facility
            for facility in candidates
            if level_id is None
            or model.facility_portal_binding(facility.facility_id).entry_level_id == level_id
        ]
        physical_candidates = [
            facility
            for facility in candidates
            if self._facility_is_on_passenger_walkable_component(
                model,
                passenger,
                facility,
            )
        ]
        candidates = [
            facility
            for facility in physical_candidates
            if not bool(getattr(facility, "is_forced_disabled", False))
        ]
        selectable = [
            facility
            for facility in candidates
            if facility.is_available_for_choice
            and model.facility_has_reservable_approach_slot(passenger, facility)
        ]
        if selectable:
            candidates = selectable
        if not physical_candidates:
            raise ValueError(
                f"Goal Graph decision region {region_id!r} has no facility portals "
                f"on level {level_id!r}"
            )

        # A temporary total closure is congestion/backpressure, not a broken
        # station topology.  Keep the physical portals as holding anchors and
        # retry selection after control state changes.
        selection = (
            self._tactical_facility_selection(
                model,
                passenger,
                region_id,
                stage,
                candidates,
            )
            if candidates
            else None
        )
        if not candidates:
            candidates = physical_candidates
        self._record_selection_hysteresis(
            model,
            passenger,
            region_id,
            selection,
        )
        preferred_facility_id = (
            selection.facility_id if selection is not None else candidates[0].facility_id
        )
        preferred_facility = next(
            facility for facility in candidates if facility.facility_id == preferred_facility_id
        )

        if selection is not None:
            model._clear_all_decision_holding_reservations(passenger)
            if (
                stage == FacilityStage.EXIT_GATE.value
                and passenger.intent == AgentIntent.EXIT_STATION.value
            ):
                model.leave_platform_waiting(passenger)
            # A decision-region target is already a physical queue-side body
            # position.  Claim it before walking begins; otherwise every agent
            # can be routed to the same tail portal and only discover the
            # conflict after arrival.  The later SELECT_FACILITY command keeps
            # or atomically switches this same stage-scoped ownership.
            model._reserve_facility_approach_slot(passenger, preferred_facility)

        approach_records = tuple(
            (facility, point)
            for facility in sorted(candidates, key=lambda item: item.facility_id)
            for point in self._facility_decision_points(model, passenger, facility)
        )
        approaches = tuple(point for _facility, point in approach_records)
        area = model.jupedsim_walkable_area(level_id)
        if selection is None:
            platform_reservation = model._platform_waiting_reservations.get(
                int(passenger.unique_id)
            )
            uses_platform_storage = stage == FacilityStage.BOARDING_DOOR.value or (
                stage == FacilityStage.EXIT_GATE.value
                and passenger.intent == AgentIntent.EXIT_STATION.value
            )
            if platform_reservation is None and uses_platform_storage:
                platform = model.platform_for_passenger(passenger)
                if platform is not None:
                    try:
                        model._reserve_platform_waiting_slot(passenger, platform)
                    except PlatformWaitingCapacityError:
                        increment_service_chain_counter(model, WAITING_CAPACITY_RETRY)
                        if stage == FacilityStage.EXIT_GATE.value:
                            # Alighting publication was licensed by this
                            # finite source-side resource. Losing it here is a
                            # model-invalid admission race, not permission to
                            # leave the new body unowned.
                            raise
                    platform_reservation = model._platform_waiting_reservations.get(
                        int(passenger.unique_id)
                    )
            if not uses_platform_storage:
                platform_reservation = None
            if platform_reservation is not None:
                target = platform_reservation.point
                model._clear_vacated_decision_holding_reservations(
                    passenger,
                    schedule=True,
                )
                self._record_decision_context(
                    passenger,
                    region_id,
                    candidates,
                    target,
                    preferred_facility_id=preferred_facility_id,
                )
                return target
            owned_facility_id = passenger.facility_approach_facility_ids_by_stage.get(stage)
            owned_slot_index = passenger.facility_approach_slots_by_stage.get(stage)
            owned_facility = next(
                (facility for facility in candidates if facility.facility_id == owned_facility_id),
                None,
            )
            if owned_facility is not None and owned_slot_index is not None:
                target = model._facility_approach_slot_position(
                    owned_facility,
                    owned_slot_index,
                )
                model._clear_vacated_decision_holding_reservations(
                    passenger,
                    schedule=True,
                )
                self._record_decision_context(
                    passenger,
                    region_id,
                    candidates,
                    target,
                    preferred_facility_id=owned_facility.facility_id,
                )
                return target
            if stage == FacilityStage.BOARDING_DOOR.value and any(
                passenger in platform.waiting for platform in model.platforms
            ):
                local = self._local_facilities_at_position(
                    model,
                    passenger,
                    candidates,
                    passenger.pos,
                    area,
                )
                if local:
                    model._clear_vacated_decision_holding_reservations(
                        passenger,
                        schedule=True,
                    )
                    self._record_decision_context(
                        passenger,
                        region_id,
                        local,
                        passenger.pos,
                        preferred_facility_id=preferred_facility_id,
                    )
                    return tuple(passenger.pos)
            try:
                target = model._reserve_decision_holding_slot(
                    passenger,
                    region_id,
                    approaches,
                )
            except DecisionHoldingCapacityError:
                # A published body without a finite downstream owner is a
                # model-invalid state, not backpressure.  Demand sources and
                # upstream facilities must reserve ownership before release;
                # fail closed here if that contract was violated.
                raise
            self._record_decision_context(
                passenger,
                region_id,
                candidates,
                target,
                preferred_facility_id=preferred_facility_id,
            )
            return target
        decision_region = self._decision_region_domain(model, approaches, area)
        passenger_point = ShapelyPoint(passenger.pos)
        local_at_position = self._local_facilities_at_position(
            model,
            passenger,
            candidates,
            passenger.pos,
            area,
        )
        if decision_region.covers(passenger_point) and any(
            facility.facility_id == preferred_facility_id for facility in local_at_position
        ):
            self._record_decision_context(
                passenger,
                region_id,
                local_at_position,
                passenger.pos,
                preferred_facility_id=preferred_facility_id,
            )
            return tuple(passenger.pos)
        preferred_records = tuple(
            record for record in approach_records if record[0].facility_id == preferred_facility_id
        )
        nearest_facility, nearest = min(
            preferred_records or approach_records,
            key=lambda record: self._distance(passenger.pos, record[1]),
        )
        if selection is not None:
            nearest = model._safe_facility_queue_approach_target(
                passenger,
                preferred_facility,
            )
        target = project_to_safe_point(
            area,
            nearest,
            clearance=max(0.02, model.scenario.jupedsim_agent_radius_units * 1.05),
            require_inside=False,
        )
        local = self._local_facilities_at_position(
            model,
            passenger,
            candidates,
            target,
            area,
        )
        self._record_decision_context(
            passenger,
            region_id,
            local or (nearest_facility,),
            target,
            preferred_facility_id=preferred_facility_id,
        )
        return target

    def local_decision_facilities(
        self,
        model,
        passenger,
        region_id: str,
        candidates,
    ):
        """Return only facilities physically observable at this decision point."""

        region = self._base_region(region_id)
        stage = _DECISION_REGION_STAGES.get(region)
        if stage is None:
            return tuple(candidates)
        recorded_ids = set(passenger.decision_facility_ids_by_region.get(region, ()))
        if recorded_ids:
            return tuple(
                facility
                for facility in candidates
                if facility.spec.stage == stage and facility.facility_id in recorded_ids
            )
        area = model.jupedsim_walkable_area(passenger.current_level_id)
        local = self._local_facilities_at_position(
            model,
            passenger,
            candidates,
            passenger.pos,
            area,
        )
        return local

    def _local_facilities_at_position(
        self,
        model,
        passenger,
        candidates,
        position,
        area,
    ):
        return tuple(
            facility
            for facility in candidates
            if (
                passenger.current_level_id is None
                or model.facility_portal_binding(facility.facility_id).entry_level_id
                == passenger.current_level_id
            )
            and self._has_local_portal_access(
                model,
                position,
                self._facility_decision_points(model, passenger, facility),
                area,
            )
        )

    def _record_decision_context(
        self,
        passenger,
        region_id: str,
        facilities,
        target: tuple[float, float],
        *,
        preferred_facility_id: str,
    ) -> None:
        region = self._base_region(region_id)
        passenger.decision_facility_ids_by_region[region] = tuple(
            sorted(facility.facility_id for facility in facilities)
        )
        passenger.decision_target_by_region[region] = tuple(target)
        passenger.decision_preferred_facility_id_by_region[region] = preferred_facility_id

    def _tactical_facility_selection(
        self,
        model,
        passenger,
        region_id: str,
        stage: str,
        candidates,
        *,
        current_facility_id: str | None = None,
    ):
        """Choose a physical observation catchment by auditable generalized cost."""

        region = self._base_region(region_id)
        if current_facility_id is None:
            current_facility_id = passenger.decision_preferred_facility_id_by_region.get(region)
        reconsider_after_seconds = (
            passenger.decision_reconsider_after_seconds_by_region.get(region)
            if current_facility_id is not None
            else None
        )
        observations = build_goal_facility_observations(
            model,
            passenger,
            stage,
            list(candidates),
            goal_node_id=passenger.goal_runtime.state.current_node_id,
        )
        return MinimumPerceivedCostSelector().choose(
            stage,
            DecisionObservation(
                time_seconds=float(model.current_time_seconds),
                current_region_id=region_id,
                candidates=observations,
                committed_facility_id=current_facility_id,
                reconsider_after_seconds=reconsider_after_seconds,
                commitment_duration_seconds=float(model.scenario.facility_commitment_seconds),
                replan_cooldown_seconds=float(model.scenario.facility_replan_cooldown_seconds),
                minimum_improvement_seconds=float(
                    model.scenario.facility_replan_minimum_improvement_seconds
                ),
            ),
        )

    def _record_selection_hysteresis(
        self,
        model,
        passenger,
        region_id: str,
        selection,
    ) -> None:
        if selection is None:
            return
        region = self._base_region(region_id)
        previous = passenger.decision_preferred_facility_id_by_region.get(region)
        if previous is None or previous == selection.facility_id:
            return
        passenger.decision_reconsider_after_seconds_by_region[region] = float(
            model.current_time_seconds
        ) + float(model.scenario.facility_replan_cooldown_seconds)

    def decision_context_needs_reroute(
        self,
        model,
        passenger,
        region_id: str,
        candidates,
    ) -> bool:
        """Detect a stale tactical catchment without selecting a remote portal."""

        region = self._base_region(region_id)
        stage = _DECISION_REGION_STAGES.get(region)
        recorded_ids = set(passenger.decision_facility_ids_by_region.get(region, ()))
        target = passenger.decision_target_by_region.get(region)
        if stage is None or not recorded_ids:
            return False
        if target is None:
            return True
        if region in passenger.decision_holding_target_by_region:
            live_candidates = tuple(
                facility
                for facility in candidates
                if facility.spec.stage == stage
                and not bool(getattr(facility, "is_forced_disabled", False))
            )
            if not live_candidates:
                return False
            # A holding context records only the portals that were viable when
            # it was compiled. Dynamic recovery can make a different bank live
            # while the old one remains saturated. Re-evaluate the complete
            # current stage here; restricting the observation to recorded_ids
            # strands every waiting body behind the first one-slot claimant.
            selection = self._tactical_facility_selection(
                model,
                passenger,
                region_id,
                stage,
                live_candidates,
            )
            return selection is not None
        if (
            passenger.intent == AgentIntent.EVACUATE_STATION.value
            and stage == FacilityStage.VERTICAL_TRANSFER.value
            and passenger.evacuation_facility_path
            and passenger.evacuation_facility_path[0] not in recorded_ids
        ):
            return True
        area = model.jupedsim_walkable_area(passenger.current_level_id)
        viable_recorded_ids: set[str] = set()
        for facility in candidates:
            if facility.facility_id not in recorded_ids or facility.spec.stage != stage:
                continue
            if bool(getattr(facility, "is_forced_disabled", False)):
                continue
            if (
                passenger.current_level_id is not None
                and model.facility_portal_binding(facility.facility_id).entry_level_id
                != passenger.current_level_id
            ):
                continue
            if not self._has_local_portal_access(
                model,
                target,
                self._facility_decision_points(model, passenger, facility),
                area,
            ):
                continue
            if stage != FacilityStage.BOARDING_DOOR.value and (
                not facility.is_available_for_choice
                or not model.facility_has_reservable_approach_slot(
                    passenger,
                    facility,
                )
            ):
                continue
            viable_recorded_ids.add(facility.facility_id)
        if not viable_recorded_ids:
            # If every candidate is currently ineligible, there is nowhere to
            # reroute.  Remaining in this physical decision region lets the
            # goal reducer emit a time-delayed wait instead of synchronously
            # re-entering the same region forever.
            selection = self._tactical_facility_selection(
                model,
                passenger,
                region_id,
                stage,
                candidates,
            )
            if selection is None or selection.facility_id in recorded_ids:
                return False
            return True

        current_facility_id = passenger.decision_preferred_facility_id_by_region.get(region)
        if current_facility_id not in viable_recorded_ids:
            current_facility_id = min(viable_recorded_ids)
        selection = self._tactical_facility_selection(
            model,
            passenger,
            region_id,
            stage,
            candidates,
            current_facility_id=current_facility_id,
        )
        if selection is None:
            # The physical catchment is still valid but every observed service
            # is temporarily ineligible (for example, train doors are closed).
            # Stay put and let the reducer wait for a later availability event.
            return False
        if selection.facility_id not in recorded_ids:
            return True
        self._record_selection_hysteresis(
            model,
            passenger,
            region_id,
            selection,
        )
        passenger.decision_preferred_facility_id_by_region[region] = selection.facility_id
        return False

    def clear_decision_context(
        self,
        passenger,
        region_id: str,
        *,
        preserve_preference: bool = False,
    ) -> None:
        region = self._base_region(region_id)
        passenger.model._clear_decision_holding_reservation(passenger, region)
        passenger.decision_facility_ids_by_region.pop(region, None)
        passenger.decision_target_by_region.pop(region, None)
        if not preserve_preference:
            passenger.decision_preferred_facility_id_by_region.pop(region, None)
            passenger.decision_reconsider_after_seconds_by_region.pop(region, None)

    def _membership_region_target(
        self,
        model,
        passenger,
        region_id: str,
    ) -> tuple[float, float]:
        stage = (
            FacilityStage.ENTRY_GATE.value
            if region_id == "paid_hall"
            else FacilityStage.VERTICAL_TRANSFER.value
        )
        facilities = model._facilities_for_stage(stage)
        assigned = model.facilities_by_id.get(passenger.assigned_facility_id)
        ordered = [assigned] if assigned is not None and assigned.spec.stage == stage else []
        ordered.extend(
            facility
            for facility in sorted(facilities, key=lambda item: item.facility_id)
            if facility not in ordered
        )
        level_id = passenger.current_level_id
        anchors = [
            facility
            for facility in ordered
            if level_id is None
            or model.facility_portal_binding(facility.facility_id).exit_level_id == level_id
        ]
        if not anchors:
            raise ValueError(
                f"Goal Graph membership region {region_id!r} has no service exits "
                f"on level {level_id!r}"
            )
        completed_position = getattr(passenger, "last_completed_facility_position", None)
        completed_facility_id = getattr(passenger, "last_completed_facility_id", None)
        completed_facility = next(
            (item for item in anchors if item.facility_id == completed_facility_id),
            None,
        )
        if (
            completed_facility is not None
            and completed_position is not None
            and getattr(passenger, "last_completed_facility_event_id", None) is not None
            and getattr(passenger, "last_completed_facility_level_id", None) == level_id
            and self._distance(passenger.pos, completed_position) <= 1e-6
        ):
            return tuple(passenger.pos)
        facility = min(
            anchors,
            key=lambda item: self._distance(
                passenger.pos,
                model.facility_portal_binding(item.facility_id).exit_point,
            ),
        )
        exit_position = tuple(model.facility_portal_binding(facility.facility_id).exit_point)
        coverage_radius = max(
            float(model.scenario.jupedsim_target_radius_units),
            float(getattr(facility.spec, "traversal_width_m", 0.0) or 0.0) / 2.0
            + float(model.scenario.jupedsim_agent_radius_units),
        )
        if self._distance(passenger.pos, exit_position) <= coverage_radius:
            return tuple(passenger.pos)
        return exit_position

    def _physical_region_route(
        self,
        model,
        passenger,
        target: tuple[float, float],
    ) -> tuple[tuple[float, float], ...]:
        route = model._physical_route_for_points(
            passenger,
            (target,),
            level_id=passenger.current_level_id,
            include_navigation_waypoints=True,
        )
        return route or (target,)

    def _apply_target_platform_constraints(self, model, passenger) -> None:
        if passenger.target_line_id is not None:
            passenger.assigned_line_id = passenger.target_line_id
        if passenger.target_direction is not None:
            passenger.assigned_direction = passenger.target_direction
        candidates = list(model.platforms)
        if passenger.assigned_line_id is not None:
            candidates = [item for item in candidates if item.line_id == passenger.assigned_line_id]
        if passenger.assigned_direction is not None:
            candidates = [
                item for item in candidates if item.direction == passenger.assigned_direction
            ]
        if len(candidates) == 1:
            passenger.assigned_platform_id = candidates[0].platform_id

    def _base_region(self, region_id: str) -> str:
        parts = region_id.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return region_id

    def _distance(
        self,
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return hypot(left[0] - right[0], left[1] - right[1])
