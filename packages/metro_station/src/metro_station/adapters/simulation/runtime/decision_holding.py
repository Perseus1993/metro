from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from shapely.geometry import Point as ShapelyPoint

from ..movement.dynamic_body_clearance import minimum_body_clearance


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

        # A passenger may own at most one tactical holding position.  Keeping
        # stage changes atomic prevents stale positions from reducing capacity
        # or being mistaken for live physical ownership.
        self._clear_all_decision_holding_reservations(passenger)

        candidates = self._decision_holding_candidates(
            level_id,
            region_id=region,
            anchors=anchors,
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

    def _decision_holding_candidates(
        self,
        level_id: str,
        *,
        region_id: str,
        anchors: tuple[Point, ...],
    ) -> tuple[Point, ...]:
        # Slots are finite compiler output, not an unbounded runtime grid over
        # the whole level.
        cached = self.layout_graph.decision_holding_slots(
            str(region_id),
            str(level_id),
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
        passenger_id = int(passenger.unique_id)
        points: list[Point] = []
        for other in tuple(getattr(self, "passengers", ())):
            if (
                int(other.unique_id) == passenger_id
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
        anchors = tuple(
            self.facility_portal_binding(door.facility_id).entry_point
            for door in self.boarding_doors_for_platform(platform)
        )
        slots = tuple(self.layout_graph.platform_waiting_slots())
        ordered = sorted(
            slots,
            key=lambda point: (
                min(
                    (
                        hypot(point[0] - anchor[0], point[1] - anchor[1])
                        for anchor in anchors
                    ),
                    default=0.0,
                ),
                point[1],
                point[0],
            ),
        )
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
        for point in ordered:
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
