from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from shapely.geometry import Point as ShapelyPoint

from ..movement.dynamic_body_clearance import minimum_body_clearance
from .platform_waiting_geometry import (
    platform_waiting_slot_clears_boarding_crossings,
    platform_waiting_slot_is_intent_eligible,
)
Point = tuple[float, float]


class DecisionHoldingCapacityError(RuntimeError):
    """No body-clear standing position remains in a decision holding area."""


class PlatformWaitingCapacityError(RuntimeError):
    """No body-clear standing position remains in a platform waiting area."""

@dataclass(frozen=True)
class DecisionHoldingReservation:
    passenger_id: int
    level_id: str
    region_id: str
    point: Point
    walkable_area_revision: int


@dataclass(frozen=True)
class PlatformWaitingReservation:
    passenger_id: int
    platform_id: str
    level_id: str
    point: Point


class DecisionHoldingMixin:
    """Own body-clear waiting positions outside facility approach queues.

    A passenger that cannot currently select a facility is still a physical
    body.  It must not wait on an unowned approach/queue slot, because a later
    queue owner may legitimately use that same position.  This registry gives
    every such passenger one exclusive standing target until selection,
    replanning, evacuation rerooting, or departure releases it.
    """

    def _reserve_decision_holding_slot(
        self,
        passenger,
        region_id: str,
        anchors: tuple[Point, ...],
    ) -> Point:
        passenger_id = int(passenger.unique_id)
        level_id = passenger.current_level_id
        if level_id is None:
            raise DecisionHoldingCapacityError(
                f"passenger {passenger_id} cannot reserve a decision holding "
                "slot without a current level"
            )
        region = str(region_id).split(":", 1)[0]
        owner_key = (passenger_id, region)
        existing = self._decision_holding_reservations.get(owner_key)
        if existing is not None and existing.level_id == level_id:
            revision = int(getattr(self, "_walkable_area_revision", 0))
            area = self.jupedsim_walkable_area(level_id)
            if (
                existing.walkable_area_revision == revision
                and area.buffer(-float(self.scenario.jupedsim_agent_radius_units)).covers(
                    ShapelyPoint(existing.point)
                )
            ):
                return existing.point

        # Keep a still-occupied former slot through a tactical handoff.  The
        # new target and the body it will leave are both finite resources until
        # physical clearance makes the former ownership safe to release.
        self._clear_vacated_decision_holding_reservations(passenger)

        candidates = self._available_decision_holding_slots(
            level_id=level_id,
            region_id=region,
            anchors=anchors,
            passenger=passenger,
            additional_region_ids=self._decision_holding_upstream_region_ids(
                getattr(passenger, "intent", ""),
                region,
            ),
        )
        for point in candidates:
            spatial_key = self._decision_holding_spatial_key(level_id, point)
            reservation = DecisionHoldingReservation(
                passenger_id=passenger_id,
                level_id=level_id,
                region_id=region,
                point=point,
                walkable_area_revision=int(
                    getattr(self, "_walkable_area_revision", 0)
                ),
            )
            self._decision_holding_reservations[owner_key] = reservation
            self._decision_holding_slot_owners[spatial_key] = passenger_id
            passenger.decision_holding_target_by_region[region] = point
            return point

        raise DecisionHoldingCapacityError(
            f"decision holding area {region!r} on level {level_id!r} has no "
            f"body-clear slot for passenger {passenger_id}"
        )

    def _available_decision_holding_slots(
        self,
        *,
        level_id: str,
        region_id: str,
        anchors: tuple[Point, ...],
        passenger=None,
        additional_region_ids: tuple[str, ...] = (),
    ) -> tuple[Point, ...]:
        """Return slots that the normal reservation path could claim now.

        This is deliberately side-effect free so an upstream demand source can
        prove that a newly published body will receive finite physical
        ownership.  Passing ``passenger`` excludes that body from the live-body
        clearance check, exactly as the committing reservation path does.
        """

        candidates = self._decision_holding_candidates(
            level_id,
            region_id=str(region_id).split(":", 1)[0],
            anchors=anchors,
            additional_region_ids=additional_region_ids,
        )
        if (
            passenger is not None
            and str(getattr(passenger, "intent", "")) == "enter_and_board"
            and str(region_id).split(":", 1)[0] == "boarding_decision"
        ):
            # A boarding queue is a dense one-way snake.  Compiler cells on
            # its downstream side remain valid for alighters approaching from
            # the train, but an entering passenger would have to cross the
            # occupied queue lattice to reach them.  Restrict that intent to
            # cells upstream of at least one boarding-queue tail.
            candidates = tuple(
                point
                for point in candidates
                if self._boarding_holding_slot_is_upstream(level_id, point)
            )
        minimum_center_distance = minimum_body_clearance(self)
        live_body_points = self._decision_holding_live_body_points(
            passenger,
            level_id=level_id,
        )
        platform_waiting_points = tuple(
            reservation.point
            for reservation in self._platform_waiting_reservations.values()
            if reservation.level_id == level_id
        )
        available: list[Point] = []
        for point in candidates:
            spatial_key = self._decision_holding_spatial_key(level_id, point)
            if spatial_key in self._decision_holding_slot_owners:
                continue
            if any(
                hypot(point[0] - other[0], point[1] - other[1])
                < minimum_center_distance - 1e-9
                for other in (*live_body_points, *platform_waiting_points)
            ):
                continue
            available.append(point)
        return tuple(available)

    def _boarding_holding_slot_is_upstream(
        self,
        level_id: str,
        point: Point,
    ) -> bool:
        tolerance = (
            max(
                float(self.scenario.jupedsim_agent_radius_units)
                * float(self.scenario.jupedsim_clearance_multiplier),
                float(self.scenario.personal_space_units),
            )
            + 0.001
        ) * 0.5
        bindings = (
            *self.layout_graph.facility_portal_bindings,
            *self.layout_graph.facility_portal_binding_variants,
        )
        directional = tuple(
            binding
            for binding in bindings
            if binding.stage == "boarding_door"
            and binding.entry_level_id == level_id
            and hypot(
                binding.approach_point[0] - binding.entry_point[0],
                binding.approach_point[1] - binding.entry_point[1],
            )
            > 1e-6
        )
        if not directional:
            return True
        for binding in directional:
            tail = binding.approach_point
            dx = tail[0] - binding.entry_point[0]
            dy = tail[1] - binding.entry_point[1]
            length = hypot(dx, dy)
            upstream_progress = (
                (point[0] - tail[0]) * dx + (point[1] - tail[1]) * dy
            ) / length
            if upstream_progress >= -tolerance:
                return True
        return False

    def _decision_holding_candidates(
        self,
        level_id: str,
        *,
        region_id: str,
        anchors: tuple[Point, ...],
        additional_region_ids: tuple[str, ...] = (),
    ) -> tuple[Point, ...]:
        # Slots are finite compiler output, not an unbounded runtime grid over
        # the whole level.
        region_ids = tuple(
            dict.fromkeys(
                (
                    str(region_id),
                    *(str(value) for value in additional_region_ids),
                )
            )
        )
        cached = tuple(
            point
            for candidate_region_id in region_ids
            for point in self.layout_graph.decision_holding_slots(
                candidate_region_id,
                str(level_id),
            )
        )
        radius = max(0.02, float(self.scenario.jupedsim_agent_radius_units))
        current_domain = self.jupedsim_walkable_area(level_id).buffer(-radius)
        cached = tuple(
            point for point in cached if current_domain.covers(ShapelyPoint(point))
        )

        anchor_points = anchors or (tuple(self.layout_graph.geometry.platform_center),)
        return tuple(
            sorted(
                cached,
                key=lambda point: (
                    min(
                        hypot(point[0] - anchor[0], point[1] - anchor[1])
                        for anchor in anchor_points
                    ),
                    point[1],
                    point[0],
                ),
            )
        )

    @staticmethod
    def _decision_holding_upstream_region_ids(
        intent: str,
        region_id: str,
    ) -> tuple[str, ...]:
        """Return finite same-side staging pools upstream of a decision area."""

        if (
            str(intent) == "exit_station"
            and str(region_id).split(":", 1)[0] == "exit_gate_decision"
        ):
            # Alighting starts beyond the platform-side boarding decision
            # area.  Its compiler-certified cells are a safe upstream staging
            # pool on the same paid-side path to the exit gates; the global
            # spatial owner registry still makes these cells exclusive with
            # boarding demand.
            return ("boarding_decision",)
        return ()

    def _decision_holding_protected_points(self, level_id: str) -> tuple[Point, ...]:
        points: list[Point] = []
        bindings = (
            *self.layout_graph.facility_portal_bindings,
            *self.layout_graph.facility_portal_binding_variants,
        )
        for binding in bindings:
            if binding.entry_level_id == level_id:
                points.extend(binding.approach_slots)
                points.extend(binding.queue_slots)
                points.append(binding.entry_point)
            if binding.exit_level_id == level_id:
                points.append(binding.exit_point)
        return tuple(points)

    def _decision_holding_live_body_points(
        self,
        passenger,
        *,
        level_id: str,
    ) -> tuple[Point, ...]:
        passenger_id = (
            None if passenger is None else int(passenger.unique_id)
        )
        points: list[Point] = []
        for other in tuple(getattr(self, "passengers", ())):
            if (
                (
                    passenger_id is not None
                    and int(other.unique_id) == passenger_id
                )
                or other.current_level_id != level_id
            ):
                continue
            points.append(tuple(other.pos))
            target = getattr(other, "target", None)
            if target is not None:
                points.append(tuple(target))
        return tuple(points)

    def _clear_decision_holding_reservation(
        self,
        passenger,
        region_id: str,
    ) -> None:
        passenger_id = int(passenger.unique_id)
        region = str(region_id).split(":", 1)[0]
        reservation = self._decision_holding_reservations.pop(
            (passenger_id, region),
            None,
        )
        self._decision_holding_release_pending.discard((passenger_id, region))
        passenger.decision_holding_target_by_region.pop(region, None)
        if reservation is None:
            return
        spatial_key = self._decision_holding_spatial_key(
            reservation.level_id,
            reservation.point,
        )
        if self._decision_holding_slot_owners.get(spatial_key) == passenger_id:
            del self._decision_holding_slot_owners[spatial_key]

    def _clear_all_decision_holding_reservations(self, passenger) -> None:
        passenger_id = int(passenger.unique_id)
        regions = tuple(
            region
            for owner_id, region in self._decision_holding_reservations
            if owner_id == passenger_id
        )
        for region in regions:
            self._clear_decision_holding_reservation(passenger, region)
        passenger.decision_holding_target_by_region.clear()

    def _clear_vacated_decision_holding_reservations(
        self,
        passenger,
        *,
        schedule: bool = False,
    ) -> None:
        passenger_id = int(passenger.unique_id)
        pending = self._decision_holding_release_pending
        if schedule:
            pending.update(
                key for key in self._decision_holding_reservations if key[0] == passenger_id
            )
        if not any(owner_id == passenger_id for owner_id, _region in pending):
            return
        level_id = getattr(passenger, "current_level_id", None)
        position = tuple(passenger.pos)
        clearance = minimum_body_clearance(self)
        regions = tuple(
            region
            for (owner_id, region), reservation in self._decision_holding_reservations.items()
            if owner_id == passenger_id
            and (owner_id, region) in pending
            and (
                reservation.level_id != level_id
                or hypot(
                    position[0] - reservation.point[0],
                    position[1] - reservation.point[1],
                )
                >= clearance - 1e-9
            )
        )
        for region in regions:
            self._clear_decision_holding_reservation(passenger, region)

    def _reserve_platform_waiting_slot(self, passenger, platform) -> Point:
        passenger_id = int(passenger.unique_id)
        platform_id = str(platform.platform_id)
        level_id = passenger.current_level_id
        if level_id is None:
            raise PlatformWaitingCapacityError(
                f"passenger {passenger_id} cannot reserve a platform waiting "
                "slot without a current level"
            )
        existing = self._platform_waiting_reservations.get(passenger_id)
        if (
            existing is not None
            and existing.platform_id == platform_id
            and existing.level_id == level_id
        ):
            return existing.point
        self._clear_platform_waiting_reservation(passenger)

        minimum_distance = minimum_body_clearance(self)
        door_bindings = tuple(
            self.facility_portal_binding(door.facility_id)
            for door in self.boarding_doors_for_platform(platform)
        )
        anchors = tuple(binding.entry_point for binding in door_bindings)
        queue_access_axes = tuple(
            (
                binding.approach_slots[-1],
                (
                    binding.entry_point[0] - binding.approach_slots[-1][0],
                    binding.entry_point[1] - binding.approach_slots[-1][1],
                ),
            )
            for binding in door_bindings
            if binding.approach_slots
            and hypot(
                binding.entry_point[0] - binding.approach_slots[-1][0],
                binding.entry_point[1] - binding.approach_slots[-1][1],
            )
            > 1e-6
        )
        exit_staging_anchors = tuple(
            node.position
            for node in self.layout_graph.station_graph.nodes.values()
            if node.level_id == level_id and node.kind == "zone"
        )
        entry_release_points = tuple(
            node.position
            for node in self.layout_graph.station_graph.nodes.values()
            if node.level_id == level_id
            and node.kind == "facility_exit"
            and node.facility_stage == "entry_gate"
        )
        waiting_core = self.jupedsim_walkable_area(level_id).buffer(
            -float(self.scenario.jupedsim_agent_radius_units) * 1.05
        )
        boarding_staging_anchors: list[Point] = []
        for tail, axis in queue_access_axes:
            axis_length = hypot(axis[0], axis[1])
            lateral = (axis[1] / axis_length, -axis[0] / axis_length)
            service = (tail[0] + axis[0], tail[1] + axis[1])
            # Stay in the paid-side circulation band between the gate release
            # and the boarding queue.  A fixed 10 m lateral displacement can
            # jump across a compact gate bank and put the reserved platform
            # cell back on the unpaid side; the passenger then has to walk
            # backwards through the entry holding lattice it just left.
            lateral_offset = max(2.0, min(5.0, axis_length * 0.65))
            candidates = (
                (
                    service[0] + lateral[0] * lateral_offset,
                    service[1] + lateral[1] * lateral_offset,
                ),
                (
                    service[0] - lateral[0] * lateral_offset,
                    service[1] - lateral[1] * lateral_offset,
                ),
            )
            valid = tuple(
                candidate
                for candidate in candidates
                if waiting_core.covers(ShapelyPoint(candidate))
            )
            if not valid:
                continue
            boarding_staging_anchors.append(
                min(
                    valid,
                    key=lambda candidate: (
                        min(
                            (
                                hypot(
                                    candidate[0] - release[0],
                                    candidate[1] - release[1],
                                )
                                for release in entry_release_points
                            ),
                            default=0.0,
                        ),
                        candidate,
                    ),
                )
            )
        slots = tuple(
            point
            for point in self.layout_graph.platform_waiting_slots()
            if platform_waiting_slot_is_intent_eligible(
                self,
                point,
                level_id=level_id,
                passenger=passenger,
            )
        )

        def waiting_slot_key(point: Point) -> tuple[float, ...]:
            if (
                str(getattr(passenger, "intent", "")) == "exit_station"
                and exit_staging_anchors
            ):
                return (
                    0.0,
                    min(
                        hypot(point[0] - anchor[0], point[1] - anchor[1])
                        for anchor in exit_staging_anchors
                    ),
                    0.0,
                    point[1],
                    point[0],
                )
            if boarding_staging_anchors:
                return (
                    0.0,
                    min(
                        hypot(point[0] - anchor[0], point[1] - anchor[1])
                        for anchor in boarding_staging_anchors
                    ),
                    0.0,
                    point[1],
                    point[0],
                )
            access_keys: list[tuple[float, float, float]] = []
            for tail, axis in queue_access_axes:
                axis_length = hypot(axis[0], axis[1])
                progress_toward_service = (
                    (point[0] - tail[0]) * axis[0]
                    + (point[1] - tail[1]) * axis[1]
                ) / axis_length
                access_keys.append(
                    (
                        0.0 if progress_toward_service <= 0.0 else 1.0,
                        hypot(point[0] - tail[0], point[1] - tail[1]),
                        max(0.0, progress_toward_service),
                    )
                )
            if access_keys:
                upstream, tail_distance, downstream_progress = min(access_keys)
                return (
                    upstream,
                    tail_distance,
                    downstream_progress,
                    point[1],
                    point[0],
                )
            return (
                0.0,
                min(
                    (
                        hypot(point[0] - anchor[0], point[1] - anchor[1])
                        for anchor in anchors
                    ),
                    default=0.0,
                ),
                0.0,
                point[1],
                point[0],
            )

        distance_ordered = sorted(
            slots,
            key=waiting_slot_key,
        )
        # Certificates retain a dense body-clear fallback lattice, but
        # consuming that lattice as one contiguous prefix creates an
        # operationally immobile crystal around the queue tail. Materialise a
        # deterministic sparse prefix first. The dense remainder remains
        # available, so this changes placement order rather than certified
        # capacity or the admission threshold.
        operational_spacing = max(0.8, minimum_distance * 2.5)
        bucket_size = operational_spacing
        sparse: list[Point] = []
        dense: list[Point] = []
        buckets: dict[tuple[int, int], list[Point]] = {}
        for point in distance_ordered:
            bucket = (
                int(point[0] // bucket_size),
                int(point[1] // bucket_size),
            )
            neighbors = (
                other
                for x_offset in (-1, 0, 1)
                for y_offset in (-1, 0, 1)
                for other in buckets.get(
                    (bucket[0] + x_offset, bucket[1] + y_offset),
                    (),
                )
            )
            if any(
                hypot(point[0] - other[0], point[1] - other[1])
                < operational_spacing - 1e-9
                for other in neighbors
            ):
                dense.append(point)
                continue
            sparse.append(point)
            buckets.setdefault(bucket, []).append(point)
        ordered = (*sparse, *dense)
        static_protected = self._decision_holding_protected_points(level_id)
        decision_protected = tuple(
            reservation.point
            for reservation in self._decision_holding_reservations.values()
            if reservation.level_id == level_id
        )
        platform_protected = tuple(
            reservation.point
            for reservation in self._platform_waiting_reservations.values()
            if reservation.level_id == level_id
        )
        live_body_points = self._decision_holding_live_body_points(
            passenger,
            level_id=level_id,
        )
        for point in ordered:
            if not platform_waiting_slot_clears_boarding_crossings(
                self,
                point,
                level_id=level_id,
            ):
                continue
            spatial_key = self._decision_holding_spatial_key(level_id, point)
            if spatial_key in self._platform_waiting_slot_owners:
                continue
            if any(
                hypot(point[0] - other[0], point[1] - other[1])
                < minimum_distance - 1e-9
                for other in (
                    *static_protected,
                    *decision_protected,
                    *platform_protected,
                    *live_body_points,
                )
            ):
                continue
            reservation = PlatformWaitingReservation(
                passenger_id=passenger_id,
                platform_id=platform_id,
                level_id=level_id,
                point=point,
            )
            self._platform_waiting_reservations[passenger_id] = reservation
            self._platform_waiting_slot_owners[spatial_key] = passenger_id
            return point
        raise PlatformWaitingCapacityError(
            f"platform {platform_id!r} on level {level_id!r} has no body-clear "
            f"waiting slot for passenger {passenger_id}"
        )

    def _available_platform_waiting_slot_count(
        self,
        *,
        level_id: str,
        passenger=None,
        limit: int | None = None,
    ) -> int:
        """Count finite platform cells a newly admitted body could own now."""

        minimum_distance = minimum_body_clearance(self)
        static_protected = self._decision_holding_protected_points(level_id)
        decision_protected = tuple(
            reservation.point
            for reservation in self._decision_holding_reservations.values()
            if reservation.level_id == level_id
        )
        platform_protected = tuple(
            reservation.point
            for reservation in self._platform_waiting_reservations.values()
            if reservation.level_id == level_id
        )
        live_body_points = self._decision_holding_live_body_points(
            passenger,
            level_id=level_id,
        )
        available = 0
        for point in self.layout_graph.platform_waiting_slots():
            if not platform_waiting_slot_is_intent_eligible(
                self,
                point,
                level_id=level_id,
                passenger=passenger,
            ):
                continue
            if not platform_waiting_slot_clears_boarding_crossings(
                self,
                point,
                level_id=level_id,
            ):
                continue
            spatial_key = self._decision_holding_spatial_key(level_id, point)
            if spatial_key in self._platform_waiting_slot_owners:
                continue
            if any(
                hypot(point[0] - other[0], point[1] - other[1])
                < minimum_distance - 1e-9
                for other in (
                    *static_protected,
                    *decision_protected,
                    *platform_protected,
                    *live_body_points,
                )
            ):
                continue
            available += 1
            if limit is not None and available >= max(0, int(limit)):
                return available
        return available

    def _clear_platform_waiting_reservation(self, passenger) -> None:
        passenger_id = int(passenger.unique_id)
        reservation = self._platform_waiting_reservations.pop(passenger_id, None)
        if reservation is None:
            return
        spatial_key = self._decision_holding_spatial_key(
            reservation.level_id,
            reservation.point,
        )
        if self._platform_waiting_slot_owners.get(spatial_key) == passenger_id:
            del self._platform_waiting_slot_owners[spatial_key]

    @staticmethod
    def _decision_holding_spatial_key(
        level_id: str,
        point: Point,
    ) -> tuple[str, float, float]:
        return str(level_id), round(float(point[0]), 6), round(float(point[1]), 6)
