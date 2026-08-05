from __future__ import annotations

from dataclasses import dataclass
from math import floor, hypot
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString
from shapely.ops import unary_union

from ..facilities.process import FacilityKind
from ..planning.plan import FacilityStage
from ..station.facility_portal_binding import Point
from ..station.facility_portal_binding import FacilityPortalBinding
from ..station.graph import StationGraph


def distance(left: Point, right: Point) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])


def point_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    squared_length = dx * dx + dy * dy
    if squared_length <= 1e-18:
        return distance(point, start)
    ratio = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / squared_length
    ratio = min(1.0, max(0.0, ratio))
    projection = start[0] + ratio * dx, start[1] + ratio * dy
    return distance(point, projection)


@dataclass(frozen=True)
class PointSpatialIndex:
    """Clearance-cell point lookup used by constructive path proofs."""

    cell_size: float
    buckets: dict[tuple[int, int], tuple[Point, ...]]

    @classmethod
    def build(
        cls,
        points: Iterable[Point],
        *,
        cell_size: float,
    ) -> PointSpatialIndex:
        size = max(0.001, float(cell_size))
        mutable: dict[tuple[int, int], list[Point]] = {}
        for point in points:
            key = floor(point[0] / size), floor(point[1] / size)
            mutable.setdefault(key, []).append(point)
        return cls(size, {key: tuple(value) for key, value in mutable.items()})

    def near_point(self, point: Point, *, radius: float) -> tuple[Point, ...]:
        return self._in_bounds(
            point[0] - radius,
            point[1] - radius,
            point[0] + radius,
            point[1] + radius,
        )

    def near_segment(
        self,
        start: Point,
        end: Point,
        *,
        radius: float,
    ) -> tuple[Point, ...]:
        return self._in_bounds(
            min(start[0], end[0]) - radius,
            min(start[1], end[1]) - radius,
            max(start[0], end[0]) + radius,
            max(start[1], end[1]) + radius,
        )

    def _in_bounds(
        self,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
    ) -> tuple[Point, ...]:
        min_cell_x = floor(min_x / self.cell_size)
        min_cell_y = floor(min_y / self.cell_size)
        max_cell_x = floor(max_x / self.cell_size)
        max_cell_y = floor(max_y / self.cell_size)
        return tuple(
            point
            for cell_x in range(min_cell_x, max_cell_x + 1)
            for cell_y in range(min_cell_y, max_cell_y + 1)
            for point in self.buckets.get((cell_x, cell_y), ())
        )


def gate_bank_tail_aisles(
    bindings: tuple[FacilityPortalBinding, ...],
    level_id: str,
    walkable_domain: Any,
    *,
    clearance: float,
):
    """Reserve the full cross-platform mouth aisle of each multi-lane gate bank."""

    banks: dict[tuple[str, str], list[FacilityPortalBinding]] = {}
    for binding in bindings:
        if (
            binding.entry_level_id == level_id
            and binding.kind == FacilityKind.GATE.value
            and binding.approach_slots
        ):
            banks.setdefault((binding.stage, str(binding.source_element_id)), []).append(
                binding
            )
    if not banks or walkable_domain.is_empty:
        return GeometryCollection()

    min_x, min_y, max_x, max_y = walkable_domain.bounds
    span = hypot(max_x - min_x, max_y - min_y) + clearance * 2.0
    aisles: list[Any] = []
    for bank in banks.values():
        if len(bank) < 2:
            continue
        representative = bank[0]
        representative_tail = max(
            representative.approach_slots,
            key=lambda point: distance(representative.entry_point, point),
        )
        axis = (
            representative_tail[0] - representative.entry_point[0],
            representative_tail[1] - representative.entry_point[1],
        )
        axis_length = hypot(axis[0], axis[1])
        if axis_length <= 1e-6:
            continue
        axis_unit = (axis[0] / axis_length, axis[1] / axis_length)
        lateral = (-axis_unit[1], axis_unit[0])
        tails = tuple(
            max(
                binding.approach_slots,
                key=lambda point: distance(binding.entry_point, point),
            )
            for binding in bank
        )
        longitudinal = sum(
            point[0] * axis_unit[0] + point[1] * axis_unit[1] for point in tails
        ) / len(tails) + clearance
        lateral_midpoint = sum(
            point[0] * lateral[0] + point[1] * lateral[1] for point in tails
        ) / len(tails)
        center = (
            axis_unit[0] * longitudinal + lateral[0] * lateral_midpoint,
            axis_unit[1] * longitudinal + lateral[1] * lateral_midpoint,
        )
        start = center[0] - lateral[0] * span, center[1] - lateral[1] * span
        end = center[0] + lateral[0] * span, center[1] + lateral[1] * span
        aisles.append(LineString((start, end)).buffer(clearance))
    return unary_union(aisles) if aisles else GeometryCollection()


def boarding_queue_access_corridors(
    graph: StationGraph,
    bindings: tuple[FacilityPortalBinding, ...],
    level_id: str,
    *,
    clearance: float,
):
    upstream_nodes = tuple(
        node
        for node in graph.nodes.values()
        if node.level_id == level_id
        and node.kind == "facility_exit"
        and node.facility_stage
        in {FacilityStage.ENTRY_GATE.value, FacilityStage.VERTICAL_TRANSFER.value}
    )
    if not upstream_nodes:
        upstream_nodes = tuple(
            node
            for node in graph.nodes.values()
            if node.level_id == level_id and node.kind == "zone"
        )
    lines: list[LineString] = []
    for binding in bindings:
        if (
            binding.stage != FacilityStage.BOARDING_DOOR.value
            or binding.entry_level_id != level_id
            or not binding.approach_slots
            or not upstream_nodes
        ):
            continue
        tail = binding.approach_slots[-1]
        upstream = min(
            upstream_nodes,
            key=lambda node: (distance(node.position, tail), node.node_id),
        )
        if distance(upstream.position, tail) > 1e-6:
            lines.append(LineString((upstream.position, tail)))
    if not lines:
        return GeometryCollection()
    return unary_union(lines).buffer(max(0.0, float(clearance)))


def station_walk_flow_corridors(
    graph: StationGraph,
    level_id: str,
    *,
    clearance: float,
):
    lines: list[LineString] = []
    for edge in graph.edges:
        if edge.kind != "walk" or edge.level_change:
            continue
        source = graph.nodes[edge.from_node]
        target = graph.nodes[edge.to_node]
        if source.level_id != level_id or target.level_id != level_id:
            continue
        if distance(source.position, target.position) > 1e-6:
            lines.append(LineString((source.position, target.position)))
    if not lines:
        return GeometryCollection()
    return unary_union(lines).buffer(max(0.0, float(clearance)))


__all__ = [
    "PointSpatialIndex",
    "boarding_queue_access_corridors",
    "distance",
    "gate_bank_tail_aisles",
    "point_segment_distance",
    "station_walk_flow_corridors",
]
