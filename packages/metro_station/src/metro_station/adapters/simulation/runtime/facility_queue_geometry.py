from __future__ import annotations

import sys
from dataclasses import dataclass, field
from math import hypot

from ..agents.passenger import PassengerAgent
from ..facilities.process import FacilityKind
from ..facilities.runtime import FacilityProcessAgent
from ..station.geometry import project_to_safe_point


def _approach_safe_projector():
    """Honor the legacy routing-module injection point used by test adapters."""

    routing_module = sys.modules.get(f"{__package__}.facility_queue_routing")
    if routing_module is None:
        return project_to_safe_point
    return getattr(routing_module, "project_to_safe_point", project_to_safe_point)


@dataclass(frozen=True)
class _ApproachProjectionContext:
    """Immutable dependency snapshot for one approach-capacity proof."""

    facility_id: str
    slots: tuple[tuple[float, float], ...]
    entry_level_id: str
    facility_kind: str
    facility_position: tuple[float, float]
    minimum_service_distance: float
    minimum_portal_separation: float
    projection_clearance: float
    walkable_revision: int
    walkable_area_identity: int
    projector_identity: int
    safe_projector_identity: int
    clamp_identity: int
    proof_revision: int
    walkable_area: object = field(compare=False, hash=False, repr=False)


class FacilityQueueGeometryMixin:
    """Queue-portal capacity proofs and side-effect-free walking routes."""

    def facility_portal_binding(self, facility_id: str):
        try:
            return self._active_facility_portal_bindings[facility_id]
        except KeyError as exc:
            raise KeyError(
                f"facility {facility_id!r} has no active compiled portal binding"
            ) from exc

    def activate_facility_portal_binding(
        self,
        facility: FacilityProcessAgent,
        *,
        direction: str,
        spec,
    ):
        """Atomically activate a precompiled facade and its matching service spec."""

        binding = self.layout_graph.facility_portal_binding_variant(
            facility.facility_id,
            direction,
        )
        slots = tuple(
            (float(point[0]), float(point[1])) for point in spec.queue_layout.slots
        )
        if (
            spec.facility_id != binding.facility_id
            or spec.source_element_id != binding.source_element_id
            or spec.stage != binding.stage
            or spec.kind != binding.kind
            or spec.direction != binding.direction
            or spec.position != binding.entry_point
            or spec.exit_position != binding.exit_point
            or spec.entry_level_id != binding.entry_level_id
            or spec.exit_level_id != binding.exit_level_id
            or slots != binding.queue_slots
        ):
            raise RuntimeError(
                f"facility {facility.facility_id!r} activation spec does not match "
                "its compiled portal binding"
            )
        facility.spec = spec
        self._active_facility_portal_bindings[facility.facility_id] = binding
        facility.queue.layout = spec.queue_layout
        facility.queue.max_length = binding.declared_queue_capacity
        return binding

    def _available_facility_approach_slot_indices(
        self,
        facility: FacilityProcessAgent,
    ) -> tuple[int, ...]:
        binding = self.facility_portal_binding(facility.facility_id)
        rank_by_runtime_index = {
            int(slot.runtime_slot_index): int(slot.service_rank)
            for slot in binding.queue_slot_bindings
            if slot.runtime_slot_index is not None and slot.service_rank is not None
        }
        candidates = sorted(
            self._facility_approach_slot_indices(facility),
            key=rank_by_runtime_index.__getitem__,
        )
        if not candidates:
            return ()

        # Queue list position is the desired physical slot index.  Do not send
        # an approaching body to a portal already owned by an enqueued body.
        occupied = set(facility.queue.occupied_slot_indices)
        occupied.update(facility.lifecycle_reserved_queue_slot_indices)
        mapped = self._facility_targeting_slot_indices.get(facility.facility_id, {})
        occupied.update(int(index) for index in mapped.values())

        # Older callers and a few synthetic tests may populate only the demand
        # reservation map.  Count those reservations conservatively instead of
        # pretending their portals are free.
        reservations = self._facility_targeting_reservations.get(
            facility.facility_id,
            {},
        )
        unmapped_count = max(0, len(reservations) - len(mapped))
        available = [index for index in candidates if index not in occupied]
        if occupied:
            # A one-body-wide queue cannot safely fill a hole in front of an
            # earlier pending/queued body.  Allocate new arrivals tailward of
            # the current physical frontier; released inner portals become
            # available again only after the queue compacts past them.
            occupied_ranks = tuple(
                rank_by_runtime_index[index]
                for index in occupied
                if index in rank_by_runtime_index
            )
            if occupied_ranks:
                frontier_rank = max(occupied_ranks)
                available = [
                    index
                    for index in available
                    if rank_by_runtime_index[index] > frontier_rank
                ]
        return tuple(available[unmapped_count:])

    def _facility_approach_slot_indices(
        self,
        facility: FacilityProcessAgent,
    ) -> tuple[int, ...]:
        try:
            binding = self.facility_portal_binding(facility.facility_id)
        except KeyError:
            return ()
        return binding.approach_slot_indices

    def _facility_approach_slot_position(
        self,
        facility: FacilityProcessAgent,
        slot_index: int,
    ) -> tuple[float, float]:
        binding = self.facility_portal_binding(facility.facility_id)
        try:
            position_index = binding.approach_slot_indices.index(int(slot_index))
        except ValueError as exc:
            raise RuntimeError(
                f"facility {facility.facility_id!r} has no compiled approach slot "
                f"{slot_index}"
            ) from exc
        return binding.approach_slots[position_index]

    def _facility_approach_positions(
        self,
        facility: FacilityProcessAgent,
    ) -> tuple[tuple[float, float], ...]:
        return self.facility_portal_binding(facility.facility_id).approach_slots

    def _facility_approach_projection_context(
        self,
        facility: FacilityProcessAgent,
        slots: tuple[tuple[float, float], ...],
    ) -> _ApproachProjectionContext:
        level_id = self.facility_portal_binding(facility.facility_id).entry_level_id
        if level_id is None:
            raise ValueError("facility entry level is required for approach projection")
        area = self._facility_approach_walkable_area(facility)
        personal_space = float(getattr(self.scenario, "personal_space_units", 0.8))
        radius = float(self.scenario.jupedsim_agent_radius_units)
        clearance_multiplier = float(
            getattr(self.scenario, "jupedsim_clearance_multiplier", 2.2)
        )
        projector = self._project_facility_approach_point
        clamp = self.clamp_position
        safe_projector = _approach_safe_projector()
        return _ApproachProjectionContext(
            facility_id=facility.facility_id,
            slots=slots,
            entry_level_id=level_id,
            facility_kind=str(facility.spec.kind),
            facility_position=tuple(facility._service_entry_position(0)),
            minimum_service_distance=max(1.0, personal_space * 1.25, radius * 2.5),
            minimum_portal_separation=max(
                radius * clearance_multiplier,
                personal_space * 0.5,
                0.05,
            ),
            projection_clearance=max(0.02, radius * 1.05),
            walkable_revision=int(getattr(self, "_walkable_area_revision", 0)),
            walkable_area_identity=id(area),
            projector_identity=id(getattr(projector, "__func__", projector)),
            safe_projector_identity=id(safe_projector),
            clamp_identity=id(getattr(clamp, "__func__", clamp)),
            proof_revision=int(self._facility_approach_proof_revision),
            walkable_area=area,
        )

    def _project_facility_approach_point(
        self,
        facility: FacilityProcessAgent,
        point: tuple[float, float],
        *,
        context: _ApproachProjectionContext | None = None,
    ) -> tuple[float, float]:
        target = self.clamp_position(point)
        level_id = self.facility_portal_binding(facility.facility_id).entry_level_id
        if level_id is None:
            return target
        area = (
            context.walkable_area
            if context is not None
            else self._facility_approach_walkable_area(facility)
        )
        clearance = (
            context.projection_clearance
            if context is not None
            else max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05)
        )
        return _approach_safe_projector()(
            area,
            target,
            clearance=clearance,
            require_inside=False,
        )

    def _facility_approach_walkable_area(self, facility: FacilityProcessAgent):
        level_id = self.facility_portal_binding(facility.facility_id).entry_level_id
        if level_id is None:
            raise ValueError("facility entry level is required for approach projection")
        station_graph = getattr(self.layout_graph, "station_graph", None)
        document = getattr(station_graph, "source_document", None)
        if document is not None and level_id not in {
            level.id for level in document.levels
        }:
            raise ValueError(f"unknown facility entry level {level_id!r}")
        area = self.jupedsim_walkable_area(level_id)
        if getattr(area, "is_empty", True):
            raise ValueError(f"facility entry level {level_id!r} has no walkable area")
        return area

    def route_to_facility_queue(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[tuple[float, float], ...]:
        stage = facility.spec.stage
        reserved_index = passenger.facility_approach_slots_by_stage.get(stage)
        if (
            passenger.facility_approach_facility_ids_by_stage.get(stage)
            == facility.facility_id
            and reserved_index is not None
        ):
            return self.route_to_facility_queue_slot(
                passenger,
                facility,
                reserved_index,
            )
        portals = self._facility_portals(passenger, facility)
        topology_route = self._station_graph_route_to_facility(
            passenger,
            facility,
            include_navigation_waypoints=True,
        )
        if topology_route:
            return topology_route
        return self._physical_route_for_points(
            passenger,
            (portals.approach,),
            level_id=portals.entry_level_id,
            include_navigation_waypoints=True,
        )

    def route_to_facility_queue_slot(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
        slot_index: int,
    ) -> tuple[tuple[float, float], ...]:
        """Route to an explicit compiled slot without reading mutable reservations."""

        normalized_index = int(slot_index)
        if normalized_index not in self._facility_approach_slot_indices(facility):
            raise ValueError(
                f"facility {facility.facility_id!r} has no compiled approach slot "
                f"{normalized_index}"
            )
        target = self._facility_approach_slot_position(
            facility,
            normalized_index,
        )
        binding = self.facility_portal_binding(facility.facility_id)
        ingress_anchors = self._gate_queue_ingress_anchors(
            passenger,
            facility,
            normalized_index,
        )
        include_navigation_waypoints = facility.spec.kind != FacilityKind.GATE.value
        topology_route = self._station_graph_route_to_facility(
            passenger,
            facility,
            final_target_override=target,
            final_approach_anchors=ingress_anchors,
            include_navigation_waypoints=include_navigation_waypoints,
        )
        if topology_route:
            return topology_route
        return self._physical_route_for_points(
            passenger,
            (*ingress_anchors, target),
            level_id=binding.entry_level_id,
            include_navigation_waypoints=include_navigation_waypoints,
        )

    def route_to_gate_queue_mouth(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
        slot_index: int,
    ) -> tuple[tuple[float, float], ...]:
        """Route a pending FIFO owner to the lane tail without entering it."""

        ingress = self._gate_queue_ingress_anchors(passenger, facility, int(slot_index))
        if not ingress:
            raise RuntimeError(
                f"facility {facility.facility_id!r} has no compiled gate tail ingress"
            )
        binding = self.facility_portal_binding(facility.facility_id)
        return self._physical_route_for_points(
            passenger,
            ingress,
            level_id=binding.entry_level_id,
            include_navigation_waypoints=False,
        ) or (ingress[-1],)

    def _gate_queue_ingress_anchors(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
        slot_index: int,
    ) -> tuple[tuple[float, float], ...]:
        """Enter a gate bank from its open tail aisle, never across other lanes."""

        if facility.spec.kind != FacilityKind.GATE.value:
            return ()
        binding = self.facility_portal_binding(facility.facility_id)
        slots = tuple(binding.approach_slots)
        if not slots or slot_index < 0 or slot_index >= len(slots):
            return ()
        entry = tuple(binding.entry_point)
        tail = slots[-1]
        axis = (tail[0] - entry[0], tail[1] - entry[1])
        axis_length = hypot(axis[0], axis[1])
        if axis_length <= 1e-6:
            return ()
        axis_unit = (axis[0] / axis_length, axis[1] / axis_length)
        lateral = (-axis_unit[1], axis_unit[0])
        spacing = min(
            (
                hypot(right[0] - left[0], right[1] - left[1])
                for left, right in zip(slots, slots[1:])
                if hypot(right[0] - left[0], right[1] - left[1]) > 1e-6
            ),
            default=max(0.8, float(self.scenario.personal_space_units)),
        )
        aisle_clearance = max(
            spacing,
            float(self.scenario.personal_space_units),
            float(self.scenario.jupedsim_agent_radius_units) * 2.5,
        )
        mouth = (
            tail[0] + axis_unit[0] * aisle_clearance,
            tail[1] + axis_unit[1] * aisle_clearance,
        )
        bank_bindings = tuple(
            candidate
            for candidate in self.layout_graph.facility_portal_bindings
            if candidate.kind == binding.kind
            and candidate.stage == binding.stage
            and candidate.source_element_id == binding.source_element_id
            and candidate.entry_level_id == binding.entry_level_id
            and candidate.approach_slots
        )
        tail_projections = tuple(
            candidate.approach_slots[-1][0] * lateral[0]
            + candidate.approach_slots[-1][1] * lateral[1]
            for candidate in bank_bindings
        )
        passenger_projection = (
            passenger.pos[0] * lateral[0] + passenger.pos[1] * lateral[1]
        )
        clamped_projection = min(
            max(passenger_projection, min(tail_projections)),
            max(tail_projections),
        )
        mouth_projection = mouth[0] * lateral[0] + mouth[1] * lateral[1]
        bank_entry = (
            mouth[0]
            + lateral[0] * (clamped_projection - mouth_projection),
            mouth[1]
            + lateral[1] * (clamped_projection - mouth_projection),
        )
        ordered_tail_projections = tuple(sorted(set(tail_projections)))
        mouth_index = min(
            range(len(ordered_tail_projections)),
            key=lambda index: abs(ordered_tail_projections[index] - mouth_projection),
        )
        entry_index = min(
            range(len(ordered_tail_projections)),
            key=lambda index: abs(ordered_tail_projections[index] - clamped_projection),
        )
        crossed_lanes = abs(entry_index - mouth_index)
        if crossed_lanes:
            # A passenger arriving beyond the bank used to share one exact
            # lateral-distribution waypoint with every nearer lane. Bodies
            # then formed a physical mutex at that point and could block the
            # whole bank indefinitely. Stagger each crossed-lane fan-out one
            # body-safe interval farther upstream while retaining the open
            # tail aisle and the lane-specific mouth.
            fanout_spacing = max(
                float(self.scenario.personal_space_units) * 0.75,
                float(self.scenario.jupedsim_agent_radius_units)
                * float(self.scenario.jupedsim_clearance_multiplier),
            )
            bank_entry = (
                bank_entry[0] + axis_unit[0] * fanout_spacing * crossed_lanes,
                bank_entry[1] + axis_unit[1] * fanout_spacing * crossed_lanes,
            )
        # The raw tail aisle can coincide with the radius-shrunk navigation
        # boundary. JuPedSim's wall force then balances the desired force for
        # a body moving parallel to the bank and creates a solitary local
        # minimum. Keep operational ingress anchors inside a modest wall-safe
        # core; the certified queue slots themselves remain unchanged.
        wall_clearance = max(
            float(self.scenario.jupedsim_agent_radius_units) * 1.5,
            float(self.scenario.personal_space_units) * 0.5,
        )
        area = self._facility_approach_walkable_area(facility)
        bank_entry = project_to_safe_point(
            area,
            bank_entry,
            clearance=wall_clearance,
            require_inside=False,
        )
        mouth = project_to_safe_point(
            area,
            mouth,
            clearance=wall_clearance,
            require_inside=False,
        )
        ingress = (
            (bank_entry, mouth)
            if hypot(
                bank_entry[0] - mouth[0],
                bank_entry[1] - mouth[1],
            )
            >= aisle_clearance
            else (mouth,)
        )
        return ingress

    def facility_walking_route(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[tuple[float, float], ...]:
        """Return a side-effect-free route for feasibility and walking-distance queries."""

        portals = self._facility_portals(passenger, facility)
        topology_route = self._station_graph_route_to_facility(
            passenger,
            facility,
            invoke_evacuation_router=False,
            include_navigation_waypoints=True,
        )
        if topology_route:
            return topology_route
        return self._physical_route_for_points(
            passenger,
            (portals.approach,),
            level_id=portals.entry_level_id,
            include_navigation_waypoints=True,
        )

    def _safe_facility_queue_approach_target(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[float, float]:
        # Portal compilation has already proved every selectable slot against
        # the scenario's body-safe level domain.  Runtime must consume that
        # immutable result, not project it again into a second geometry truth.
        return self._facility_queue_approach_target(passenger, facility)

    def _facility_queue_approach_target(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[float, float]:
        claimed_facility_id, stage_claim_is_corrupt = (
            self._passenger_stage_approach_claim_state(
                passenger,
                facility.spec.stage,
            )
        )
        if stage_claim_is_corrupt:
            self._clear_facility_targeting_reservation(
                passenger,
                facility.spec.stage,
                expected_facility_id=facility.facility_id,
            )
            raise RuntimeError(
                f"facility {facility.facility_id!r} approach reservation is stale"
            )
        reserved_index = (
            passenger.facility_approach_slots_by_stage.get(facility.spec.stage)
            if claimed_facility_id == facility.facility_id
            else None
        )
        allowed_indices = self._facility_approach_slot_indices(facility)
        if reserved_index is not None:
            if reserved_index not in allowed_indices:
                raise RuntimeError(
                    f"facility {facility.facility_id!r} reservation targets "
                    f"non-approach slot {reserved_index}"
                )
            return self._facility_approach_slot_position(facility, reserved_index)
        available_indices = self._available_facility_approach_slot_indices(facility)
        if available_indices:
            return self._facility_approach_slot_position(facility, available_indices[0])
        if allowed_indices:
            return self._facility_approach_slot_position(facility, allowed_indices[-1])
        raise RuntimeError(
            f"facility {facility.facility_id!r} has no body-clear compiled approach portal"
        )
