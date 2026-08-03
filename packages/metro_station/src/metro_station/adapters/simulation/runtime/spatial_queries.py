from __future__ import annotations

from collections import defaultdict
from math import cos as math_cos
from math import sin as math_sin

from ..agents.passenger import PassengerAgent
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import CROWD_INTERACTION_STATES, AgentState
from ..station.geometry import level_walkable_geometry


class SpatialQueryMixin:
    """Spatial indexing, walkable-area lookup, and crowd-density queries."""

    def active_passengers(self) -> list[PassengerAgent]:
        return [
            passenger
            for passenger in self.passengers
            if passenger.state != AgentState.DEPARTED.value
        ]

    def clamp_position(self, position: tuple[float, float]) -> tuple[float, float]:
        geom = self.layout_graph.geometry
        x, y = position
        return (
            max(1.0, min(geom.width - 1.0, x)),
            max(1.0, min(geom.height - 1.0, y)),
        )

    def jupedsim_walkable_area(self, level_id: str | None = None):
        if level_id is None:
            if self._jupedsim_walkable_area is not None:
                return self._jupedsim_walkable_area
            walkable_geometry = getattr(self.layout_graph, "walkable_geometry", None)
            if walkable_geometry is None:
                walkable_geometry = self._rectangular_jupedsim_walkable_area()
            self._jupedsim_walkable_area = self._with_active_control_obstacles(
                walkable_geometry,
                None,
            )
            return self._jupedsim_walkable_area

        if level_id in self._jupedsim_level_walkable_areas:
            return self._jupedsim_level_walkable_areas[level_id]

        station_graph = getattr(self.layout_graph, "station_graph", None)
        document = getattr(station_graph, "source_document", None)
        if document is None:
            area = self.jupedsim_walkable_area()
        else:
            area = level_walkable_geometry(
                document,
                level_id,
                getattr(
                    self.layout_graph,
                    "walkable_geometry",
                    self._rectangular_jupedsim_walkable_area(),
                ),
            )
            if area.is_empty:
                area = self.jupedsim_walkable_area()
        area = self._with_active_control_obstacles(area, level_id)
        self._jupedsim_level_walkable_areas[level_id] = area
        return area

    def invalidate_walkable_area_cache(self) -> int:
        self._jupedsim_walkable_area = None
        self._jupedsim_level_walkable_areas.clear()
        self._walkable_area_revision = int(getattr(self, "_walkable_area_revision", 0)) + 1
        replanned = self.invalidate_facility_approach_proofs(
            reason="walkable_geometry_changed",
        )
        router = getattr(self, "_physical_waypoint_router", None)
        if router is not None:
            router.clear()
        return replanned

    def _with_active_control_obstacles(self, area, level_id: str | None):
        controller = getattr(self, "control_timeline_controller", None)
        if controller is None:
            return area
        obstacles = controller.active_obstacle_geometry(level_id)
        return area if obstacles is None else area.difference(obstacles)

    def _rectangular_jupedsim_walkable_area(self):
        from shapely import Polygon

        geom = self.layout_graph.geometry
        return Polygon(
            [(0.0, 0.0), (geom.width, 0.0), (geom.width, geom.height), (0.0, geom.height)]
        )

    def vertical_transport_speed(self, passenger: PassengerAgent) -> float:
        facility = self.facilities_by_id.get(passenger.assigned_facility_id)
        if not isinstance(facility, FacilityProcessAgent):
            return self.scenario.jupedsim_desired_speed_mps
        return (
            facility.spec.travel_speed_m_s
            or (
                facility.spec.speed_units_per_tick / self.scenario.tick_seconds
                if facility.spec.speed_units_per_tick is not None
                else self.scenario.jupedsim_desired_speed_mps
            )
        )

    def rebuild_spatial_index(self) -> None:
        cells: defaultdict[tuple[int, int], list[PassengerAgent]] = defaultdict(list)
        cell_size = self._spatial_cell_size
        for passenger in self.passengers:
            if passenger.state == AgentState.DEPARTED.value:
                continue
            x, y = passenger.pos
            cells[(int(x // cell_size), int(y // cell_size))].append(passenger)
        self._spatial_index = dict(cells)

    def nearby_passengers(
        self,
        passenger: PassengerAgent,
        radius: float,
    ) -> list[tuple[PassengerAgent, float, float, float]]:
        px, py = passenger.pos
        nearby: list[tuple[PassengerAgent, float, float, float]] = []
        cell_size = self._spatial_cell_size
        cx = int(px // cell_size)
        cy = int(py // cell_size)
        cell_radius = max(1, int(radius // cell_size) + 1)
        candidates: list[PassengerAgent] = []
        for ix in range(cx - cell_radius, cx + cell_radius + 1):
            for iy in range(cy - cell_radius, cy + cell_radius + 1):
                candidates.extend(self._spatial_index.get((ix, iy), []))
        limit = self.scenario.interaction_sample_limit
        if len(candidates) > limit:
            candidates = self.random.sample(candidates, limit)

        for other in candidates:
            if other is passenger or other.state == AgentState.DEPARTED.value:
                continue
            ox, oy = other.pos
            dx = px - ox
            dy = py - oy
            dist = (dx * dx + dy * dy) ** 0.5
            if 0.001 < dist < radius:
                nearby.append((other, dx, dy, dist))
            elif dist <= 0.001:
                angle = self.random.random() * 6.283185307
                nearby.append((other, math_cos(angle), math_sin(angle), 0.001))
        return nearby

    def local_density_load(self, passenger: PassengerAgent) -> float:
        scenario = self.scenario
        load = 0.0
        for other, _dx, _dy, dist in self.nearby_passengers(passenger, scenario.crowd_radius_units):
            proximity_weight = (scenario.crowd_radius_units - dist) / scenario.crowd_radius_units
            group_weight = max(0.25, other.group_size / scenario.group_size)
            load += proximity_weight * group_weight
        return load

    def walk_speed_factor(self, passenger: PassengerAgent) -> float:
        scenario = self.scenario
        density_load = self.local_density_load(passenger)
        factor = 1.0 / (1.0 + scenario.density_slowdown_strength * density_load)
        return max(scenario.min_walk_speed_factor, min(1.0, factor))

    def desired_walk_speed_mps(self, passenger: PassengerAgent) -> float:
        free_speed = float(
            getattr(passenger, "free_walk_speed_mps", self.scenario.jupedsim_desired_speed_mps)
        )
        return free_speed * self.walk_speed_factor(passenger)

    def crowding_index(self) -> float:
        active = self.active_passengers()
        if not active:
            return 0.0
        sample_size = min(len(active), self.scenario.crowding_sample_size)
        sample = self.random.sample(active, sample_size) if len(active) > sample_size else active
        return sum(self.local_density_load(passenger) for passenger in sample) / len(sample)

    def average_walk_speed_factor(self) -> float:
        moving = [
            passenger
            for passenger in self.active_passengers()
            if passenger.state in CROWD_INTERACTION_STATES
        ]
        if not moving:
            return 1.0
        sample_size = min(len(moving), self.scenario.crowding_sample_size)
        sample = self.random.sample(moving, sample_size) if len(moving) > sample_size else moving
        return sum(self.walk_speed_factor(passenger) for passenger in sample) / len(sample)
