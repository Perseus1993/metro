from __future__ import annotations

from math import hypot

import mesa

from .base import MovableAgent
from .passenger import PassengerAgent
from ..facilities.filters import filter_facilities_for_passenger
from ..planning.plan import PlanActionKind
from ..planning.selection import pick_least_loaded


Point = tuple[float, float]


class AdminAgent(MovableAgent):
    """Station staff agent that patrols and nudges passenger facility choices."""

    def __init__(
        self,
        model: mesa.Model,
        *,
        patrol_route: list[Point] | tuple[Point, ...],
        guide_radius: float,
    ) -> None:
        super().__init__(model)
        route = list(patrol_route)
        if not route:
            route = [self.model.layout_graph.geometry.paid_hall_center]
        self.patrol_route = route
        self.guide_radius = float(guide_radius)
        self.patrol_index = 0
        self.guided_count = 0
        self.state = "patrolling"
        self.pos = route[0]
        self.target = route[1 % len(route)] if len(route) > 1 else route[0]

    def move_toward_target(self) -> bool:
        x, y = self.pos
        tx, ty = self.target
        dx = tx - x
        dy = ty - y
        dist = hypot(dx, dy)
        if dist <= 0.001:
            self.pos = self.target
            return True

        step = min(self.model.scenario.admin_patrol_speed_units_per_tick, dist)
        self.pos = self.model.clamp_position((x + dx / dist * step, y + dy / dist * step))
        return step >= dist

    def step(self) -> None:
        if self.move_toward_target():
            self.patrol_index = (self.patrol_index + 1) % len(self.patrol_route)
            self.target = self.patrol_route[(self.patrol_index + 1) % len(self.patrol_route)]
        self._guide_nearby_passengers()

    def _guide_nearby_passengers(self) -> None:
        policy = self.model.facility_choice_policy
        if not hasattr(policy, "guide_passenger"):
            return

        guided = 0
        for passenger in self.model.active_passengers():
            if (
                hypot(passenger.pos[0] - self.pos[0], passenger.pos[1] - self.pos[1])
                > self.guide_radius
            ):
                continue
            stage = self._next_facility_stage(passenger)
            if stage is None:
                continue
            facility = self._least_loaded_facility(passenger, stage)
            if facility is None:
                continue
            policy.guide_passenger(passenger.unique_id, facility.facility_id)
            guided += 1

        if guided:
            self.guided_count += guided
            self.model.audit.record(
                "admin_guided_passengers",
                source="admin_agent",
                severity="debug",
                count=guided,
                step=self.model.step_index,
                context={"admin_id": self.unique_id},
            )

    def _next_facility_stage(self, passenger: PassengerAgent) -> str | None:
        if passenger.plan.action_index >= len(passenger.plan.action_sequence):
            return None
        action = passenger.plan.action_sequence[passenger.plan.action_index]
        if (
            action.kind == PlanActionKind.CHOOSE_FACILITY.value
            and action.trigger_state == passenger.state
        ):
            return action.stage
        return None

    def _least_loaded_facility(self, passenger: PassengerAgent, stage: str):
        candidates = filter_facilities_for_passenger(
            passenger,
            stage,
            self.model._facilities_for_stage(stage),
        )
        if not candidates:
            return None
        return pick_least_loaded(
            candidates, self.model.random, lambda facility: facility.queue_persons
        )
