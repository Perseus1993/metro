from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians, sin
from typing import Any

from shapely.geometry import Point as ShapelyPoint
from shapely.ops import unary_union

from ..planning.plan import FacilityStage, RouteKey
from ..design.schema import StationDesignDocument
from ..facilities.process import FacilitySpec
from .geometry import (
    dedupe_points,
    grid_safe_points,
    level_walkable_geometry,
    project_to_safe_point,
)
from .layout_graph import LayoutEdge, LayoutGraph, LayoutNode
from .scenario import StationGeometry
from .graph import StationGraph


Point = tuple[float, float]


@dataclass(frozen=True)
class RouteCatalog:
    """Runtime route lookup facade backed by the compiled station graph."""

    _layout_graph: LayoutGraph = field(compare=False, repr=False)

    def route_for_key(
        self,
        route_key: str | RouteKey,
        start: Point,
        passenger: object | None = None,
    ) -> tuple[Point, ...]:
        return self._layout_graph.route_for_key(route_key, start, passenger)


@dataclass(frozen=True)
class RuntimeStationLayout:
    """Compiled layout contract consumed by the Mesa runtime."""

    geometry: StationGeometry
    nodes: dict[str, LayoutNode]
    edges: tuple[LayoutEdge, ...]
    facilities: tuple[FacilitySpec, ...]
    station_graph: StationGraph
    route_catalog: RouteCatalog
    walkable_geometry: Any = field(compare=False, repr=False)
    _layout_graph: LayoutGraph = field(compare=False, repr=False)
    _platform_waiting_slots: tuple[Point, ...] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    _platform_waiting_domain: Any | None = field(default=None, compare=False, repr=False)

    @classmethod
    def from_layout_graph(
        cls,
        layout_graph: LayoutGraph,
        *,
        walkable_geometry: Any,
    ) -> "RuntimeStationLayout":
        if layout_graph.station_graph is None:
            raise ValueError("RuntimeStationLayout requires a StationGraph-backed layout.")
        return cls(
            geometry=layout_graph.geometry,
            nodes=layout_graph.nodes,
            edges=layout_graph.edges,
            facilities=layout_graph.facilities,
            station_graph=layout_graph.station_graph,
            route_catalog=RouteCatalog(layout_graph),
            walkable_geometry=walkable_geometry,
            _layout_graph=layout_graph,
        )

    def route_for_key(
        self,
        route_key: str | RouteKey,
        start: Point,
        passenger: object | None = None,
    ) -> tuple[Point, ...]:
        return self.route_catalog.route_for_key(route_key, start, passenger)

    def platform_waiting_position(self, index: int) -> Point:
        slots = self._compiled_platform_waiting_slots()
        if index < len(slots):
            return slots[index]
        return self._platform_waiting_overflow_position(index, slots)

    def platform_descriptors(self) -> tuple[tuple[str, str, str], ...]:
        return self._layout_graph.platform_descriptors()

    def facilities_for_stage(self, stage: str | FacilityStage) -> tuple[FacilitySpec, ...]:
        return self._layout_graph.facilities_for_stage(stage)

    def _compiled_platform_waiting_slots(self) -> tuple[Point, ...]:
        cached = self._platform_waiting_slots
        if cached is not None:
            return cached

        domain = self._compiled_platform_waiting_domain()
        slots = self._boarding_queue_slots_in_domain(domain)
        platform_grid = grid_safe_points(domain, spacing=0.58, clearance=0.25)
        if slots:
            slots = dedupe_points((*_jitter_slots(domain, slots, clearance=0.22), *platform_grid))
        else:
            slots = platform_grid
        if not slots:
            fallback = domain.representative_point()
            slots = ((float(fallback.x), float(fallback.y)),)
        object.__setattr__(self, "_platform_waiting_slots", slots)
        return slots

    def _compiled_platform_waiting_domain(self):
        cached = self._platform_waiting_domain
        if cached is not None:
            return cached

        document = self.station_graph.source_document
        if document is None:
            raise RuntimeError("RuntimeStationLayout requires a source design document.")

        platform_level_ids = {
            node.level_id for node in self.station_graph.nodes_matching(kind="platform")
        }
        if not platform_level_ids:
            platform_level_ids = {
                facility.entry_level_id
                for facility in self.facilities
                if facility.stage == FacilityStage.BOARDING_DOOR.value
                and facility.entry_level_id is not None
            }
        domain = _platform_domain_from_document(
            document,
            platform_level_ids,
            self.walkable_geometry,
        )
        object.__setattr__(self, "_platform_waiting_domain", domain)
        return domain

    def _boarding_queue_slots_in_domain(self, domain) -> tuple[Point, ...]:
        door_slots_by_door = [
            tuple(
                slot
                for slot in facility.queue_layout.slots
                if domain.covers(ShapelyPoint(slot))
            )
            for facility in sorted(
                self.facilities,
                key=lambda item: (item.platform_id or "", item.position),
            )
            if facility.stage == FacilityStage.BOARDING_DOOR.value
        ]
        door_slots_by_door = [slots for slots in door_slots_by_door if slots]
        interleaved_slots: list[Point] = []
        if door_slots_by_door:
            max_depth = max(len(slots) for slots in door_slots_by_door)
            for depth in range(max_depth):
                for slots in door_slots_by_door:
                    if depth < len(slots):
                        interleaved_slots.append(slots[depth])
        return tuple(dedupe_points(interleaved_slots))

    def _platform_waiting_overflow_position(
        self,
        index: int,
        slots: tuple[Point, ...],
    ) -> Point:
        if not slots:
            return self._layout_graph.platform_waiting_position(index)
        tail_size = max(1, min(28, len(slots)))
        overflow_index = index - len(slots)
        base = slots[-tail_size:][overflow_index % tail_size]
        band = 1 + overflow_index // tail_size
        angle = radians((index * 137.50776405) % 360.0)
        candidate = (
            base[0] + cos(angle) * 0.32,
            base[1] + sin(angle) * 0.32 - band * 0.18,
        )
        return project_to_safe_point(
            self._compiled_platform_waiting_domain(),
            candidate,
            clearance=0.22,
            require_inside=False,
        )


def _platform_domain_from_document(
    document: StationDesignDocument,
    platform_level_ids: set[str],
    walkable_geometry,
):
    if not platform_level_ids:
        return walkable_geometry
    domains = [
        level_walkable_geometry(document, level_id, walkable_geometry)
        for level_id in sorted(platform_level_ids)
    ]
    domains = [domain for domain in domains if not domain.is_empty]
    if not domains:
        return walkable_geometry
    return unary_union(domains)


def _jitter_slots(domain, slots: tuple[Point, ...], *, clearance: float) -> tuple[Point, ...]:
    jittered: list[Point] = []
    for index, slot in enumerate(slots):
        angle = radians((index * 137.50776405) % 360.0)
        radius = 0.08 + 0.24 * ((index * 37) % 11) / 10.0
        candidate = (
            round(slot[0] + cos(angle) * radius, 4),
            round(slot[1] + sin(angle) * radius, 4),
        )
        if not domain.covers(ShapelyPoint(candidate)):
            candidate = slot
        jittered.append(
            project_to_safe_point(
                domain,
                candidate,
                clearance=clearance,
                require_inside=False,
            )
        )
    return tuple(dedupe_points(jittered))
