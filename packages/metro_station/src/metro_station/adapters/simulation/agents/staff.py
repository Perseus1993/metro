from __future__ import annotations

from math import hypot

import mesa

from .base import MovableAgent


Point = tuple[float, float]


class AdminAgent(MovableAgent):
    """Station staff agent that patrols or holds a guidance position."""

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
        self.guidance_target_id: str | None = None
        self.guidance_level_id: str | None = None
        self.pos = route[0]
        self.target = route[1 % len(route)] if len(route) > 1 else route[0]

    def start_guidance(
        self,
        *,
        target_position: Point,
        target_id: str,
        level_id: str | None,
    ) -> None:
        self.guidance_target_id = target_id
        self.guidance_level_id = level_id
        self.target = target_position
        self.state = "moving_to_guidance"

    def stop_guidance(self) -> None:
        self.guidance_target_id = None
        self.guidance_level_id = None
        self.state = "patrolling"
        self.target = self.patrol_route[(self.patrol_index + 1) % len(self.patrol_route)]

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
            if self.guidance_target_id is not None:
                self.state = "guiding"
                return
            self.patrol_index = (self.patrol_index + 1) % len(self.patrol_route)
            self.target = self.patrol_route[(self.patrol_index + 1) % len(self.patrol_route)]
