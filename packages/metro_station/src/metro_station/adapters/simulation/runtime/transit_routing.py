from __future__ import annotations

from math import cos as math_cos
from math import sin as math_sin

from shapely.geometry import Point as ShapelyPoint

from ..agents.passenger import PassengerAgent
from ..agents.transit import PlatformAgent, TrainAgent
from ..facilities.filters import filter_boarding_doors_for_platform
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import FacilityStage, RouteKey
from ..station.geometry import project_to_safe_point


class TransitRoutingMixin:
    """Resolve platforms, trains, boarding doors, and dispersed route targets."""

    def join_platform(self, passenger: PassengerAgent) -> bool:
        platform = self.platform_for_passenger(passenger)
        if platform is None:
            return False
        platform.join_waiting(passenger)
        if passenger in platform.waiting:
            target = self._reserve_platform_waiting_slot(passenger, platform)
            passenger.set_passive_layout_target(
                target,
                goal_kind="waiting",
                goal_label="platform waiting slot",
            )
            # The durable platform cell now owns the body.  Release the
            # temporary door-approach claim so upstream gates can admit the
            # next passenger; a later train-available poll must reacquire an
            # approach before this passenger leaves its waiting cell.
            self._clear_facility_targeting_reservation(
                passenger,
                FacilityStage.BOARDING_DOOR.value,
            )
        return True

    def leave_platform_waiting(self, passenger: PassengerAgent) -> None:
        for platform in self.platforms:
            if passenger in platform.waiting:
                platform.waiting.remove(passenger)
        self._clear_platform_waiting_reservation(passenger)

    def platform_for_passenger(self, passenger: PassengerAgent) -> PlatformAgent | None:
        if passenger.assigned_platform_id is not None:
            platform = self.platforms_by_id.get(passenger.assigned_platform_id)
            if platform is not None:
                return platform
            self.audit.record(
                "assigned_platform_missing",
                source="platform_choice",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "platform_id": passenger.assigned_platform_id,
                },
            )
            passenger.last_replan_reason = "assigned_platform_missing"
            return None

        filtered = self.platforms
        if passenger.assigned_line_id is not None:
            filtered = [
                platform
                for platform in filtered
                if platform.line_id == passenger.assigned_line_id
            ]
        if passenger.assigned_direction is not None:
            filtered = [
                platform
                for platform in filtered
                if platform.direction == passenger.assigned_direction
            ]
        if len(filtered) == 1:
            return filtered[0]

        self.audit.record(
            "platform_assignment_missing",
            source="platform_choice",
            severity="error",
            step=self.step_index,
            context={
                "passenger_id": passenger.unique_id,
                "intent": passenger.intent,
                "assigned_line_id": passenger.assigned_line_id,
                "assigned_direction": passenger.assigned_direction,
                "candidate_count": len(filtered),
            },
        )
        passenger.last_replan_reason = "platform_assignment_missing"
        return None

    def boarding_doors_for_platform(self, platform: PlatformAgent) -> list[FacilityProcessAgent]:
        return filter_boarding_doors_for_platform(platform, self.boarding_doors)

    def boarding_doors_for_train(self, train: TrainAgent) -> list[FacilityProcessAgent]:
        doors = [
            door
            for door in self.boarding_doors
            if door.spec.platform_id == train.platform_id
        ]
        if doors:
            return doors
        return [
            door
            for door in self.boarding_doors
            if door.spec.line_id == train.line_id and door.spec.direction == train.direction
        ]

    def train_for_platform(self, platform: PlatformAgent) -> TrainAgent | None:
        train = self.trains_by_platform_id.get(platform.platform_id)
        if train is not None:
            return train
        for candidate in self.trains:
            if candidate.line_id == platform.line_id and candidate.direction == platform.direction:
                return candidate
        return None

    def boarding_train_for_platform(self, platform: PlatformAgent) -> TrainAgent | None:
        train = self.train_for_platform(platform)
        if train is not None and train.is_boarding:
            return train
        return None

    def train_for_facility(self, facility: FacilityProcessAgent) -> TrainAgent | None:
        platform_id = facility.spec.platform_id
        if platform_id is not None:
            return self.trains_by_platform_id.get(platform_id)
        for train in self.trains:
            if (
                train.line_id == facility.spec.line_id
                and train.direction
                == self.facility_portal_binding(facility.facility_id).direction
            ):
                return train
        return None

    def route_for_key(
        self,
        route_key: str | RouteKey,
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], ...]:
        key = route_key.value if isinstance(route_key, RouteKey) else str(route_key)
        try:
            route = self.layout_graph.route_for_key(key, passenger.pos, passenger)
        except ValueError as exc:
            self.audit.record(
                "route_planning_failed",
                source="route_planning",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "intent": passenger.intent,
                    "state": passenger.state,
                    "route_key": key,
                    "current_level_id": passenger.current_level_id,
                    "error": str(exc),
                },
            )
            passenger.last_replan_reason = f"route_planning_failed:{key}"
            return ()
        dispersed = self._disperse_route_targets(key, route, passenger)
        if key == RouteKey.CURRENT_POSITION.value:
            return dispersed
        if not dispersed:
            return ()
        return self._physical_route_for_points(passenger, (dispersed[-1],))

    def _disperse_route_targets(
        self,
        route_key: str,
        route: tuple[tuple[float, float], ...],
        passenger: PassengerAgent,
    ) -> tuple[tuple[float, float], ...]:
        if not route or route_key == RouteKey.CURRENT_POSITION.value:
            return route
        if self.layout_graph.station_graph is None:
            return route

        spread = max(0.25, min(0.75, self.scenario.jupedsim_target_radius_units * 1.35))
        dispersed: list[tuple[float, float]] = []
        for index, point in enumerate(route):
            dispersed.append(self._disperse_route_point(point, passenger, index, spread))
        return tuple(dispersed)

    def _disperse_route_point(
        self,
        point: tuple[float, float],
        passenger: PassengerAgent,
        index: int,
        spread: float,
    ) -> tuple[float, float]:
        local_domain = self.jupedsim_walkable_area().intersection(ShapelyPoint(point).buffer(1.8))
        if local_domain.is_empty:
            return point

        passenger_id = int(getattr(passenger, "unique_id", 0) or 0)
        seed = passenger_id * 1103515245 + index * 12345 + self.step_index * 97
        angle = (seed % 6283) / 1000.0
        radius = spread * (0.35 + 0.65 * ((seed // 6283) % 17) / 16.0)
        candidate = (
            point[0] + math_cos(angle) * radius,
            point[1] + math_sin(angle) * radius,
        )
        if not local_domain.covers(ShapelyPoint(candidate)):
            candidate = point
        return project_to_safe_point(
            local_domain,
            candidate,
            clearance=max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05),
            require_inside=False,
        )
