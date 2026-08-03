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

    def _available_facility_approach_slot_indices(
        self,
        facility: FacilityProcessAgent,
    ) -> tuple[int, ...]:
        candidates = list(self._facility_approach_slot_indices(facility))
        if not candidates:
            return ()

        # Queue list position is the desired physical slot index.  Do not send
        # an approaching body to a portal already owned by an enqueued body.
        occupied = set(facility.queue.occupied_slot_indices)
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
            frontier = max(occupied)
            available = [index for index in available if index > frontier]
        return tuple(available[unmapped_count:])

    def _facility_approach_slot_indices(
        self,
        facility: FacilityProcessAgent,
    ) -> tuple[int, ...]:
        layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
        slots = tuple(layout.slots)
        if not slots:
            return ()
        try:
            context = self._facility_approach_projection_context(facility, slots)
        except Exception:
            return ()
        cached = self._facility_approach_proof_cache.get(context)
        if cached is not None:
            return cached
        indices = range(len(slots))
        if context.facility_kind in {
            FacilityKind.ESCALATOR.value,
            FacilityKind.ELEVATOR.value,
            FacilityKind.STAIRS.value,
        }:
            indices = (
                index
                for index in range(1, len(slots))
                if hypot(
                    slots[index][0] - context.facility_position[0],
                    slots[index][1] - context.facility_position[1],
                )
                >= context.minimum_service_distance
            )

        unique_indices: list[int] = []
        unique_raw_points: list[tuple[float, float]] = []
        unique_points: list[tuple[float, float]] = []
        for index in indices:
            raw_point = slots[index]
            try:
                point = self._project_facility_approach_point(
                    facility,
                    raw_point,
                    context=context,
                )
            except Exception:
                # Unknown/missing level geometry or a failed safe projection
                # invalidates the capacity proof for the entire facility.
                # Returning raw coordinates here is a fail-open path into an
                # unreachable or collocated tactical portal.
                return ()
            if hypot(
                point[0] - context.facility_position[0],
                point[1] - context.facility_position[1],
            ) < context.minimum_service_distance - 1e-9:
                continue
            if any(
                hypot(raw_point[0] - other[0], raw_point[1] - other[1])
                < context.minimum_portal_separation
                for other in unique_raw_points
            ):
                continue
            if any(
                hypot(point[0] - other[0], point[1] - other[1])
                < context.minimum_portal_separation
                for other in unique_points
            ):
                continue
            unique_indices.append(index)
            unique_raw_points.append(raw_point)
            unique_points.append(point)
        result = tuple(unique_indices)
        self._facility_approach_proof_cache[context] = result
        return result

    def _facility_approach_projection_context(
        self,
        facility: FacilityProcessAgent,
        slots: tuple[tuple[float, float], ...],
    ) -> _ApproachProjectionContext:
        level_id = facility.spec.entry_level_id
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
        level_id = facility.spec.entry_level_id
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
        level_id = facility.spec.entry_level_id
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
        portals = self._facility_portals(passenger, facility)
        topology_route = self._station_graph_route_to_facility(passenger, facility)
        if topology_route:
            return topology_route
        return self._physical_route_for_points(
            passenger,
            (portals.approach,),
            level_id=portals.entry_level_id,
        )

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
        )
        if topology_route:
            return topology_route
        return self._physical_route_for_points(
            passenger,
            (portals.approach,),
            level_id=portals.entry_level_id,
        )

    def _safe_facility_queue_approach_target(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[float, float]:
        level_id = facility.spec.entry_level_id or passenger.current_level_id
        target = self.clamp_position(
            self._facility_queue_approach_target(passenger, facility)
        )
        try:
            area = self.jupedsim_walkable_area(level_id)
            return _approach_safe_projector()(
                area,
                target,
                clearance=max(
                    0.02,
                    self.scenario.jupedsim_agent_radius_units * 1.05,
                ),
                require_inside=False,
            )
        except Exception:
            return self.clamp_position(target)

    def _facility_queue_approach_target(
        self,
        passenger: PassengerAgent,
        facility: FacilityProcessAgent,
    ) -> tuple[float, float]:
        layout = getattr(facility, "approach_queue_layout", facility.spec.queue_layout)
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
        if layout.slots:
            allowed_indices = self._facility_approach_slot_indices(facility)
            if reserved_index is not None:
                if reserved_index not in allowed_indices:
                    raise RuntimeError(
                        f"facility {facility.facility_id!r} reservation targets "
                        f"non-approach slot {reserved_index}"
                    )
                return layout.slot(reserved_index)
            available_indices = self._available_facility_approach_slot_indices(facility)
            if available_indices:
                return layout.slot(available_indices[0])
            if allowed_indices:
                return layout.slot(allowed_indices[-1])
            raise RuntimeError(
                f"facility {facility.facility_id!r} has no body-clear approach portal"
            )
        slot_index = len(facility.queue) if reserved_index is None else reserved_index
        if layout.slots:
            slot_index = min(max(0, slot_index), len(layout.slots) - 1)
        return layout.slot(max(0, slot_index))
