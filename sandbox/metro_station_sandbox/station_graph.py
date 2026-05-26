from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from math import hypot
from typing import Any

from shapely.geometry import LineString

from .agent_plan import AgentIntent, FacilityStage
from .design.helpers import (
    gate_direction as _gate_direction,
    platform_direction as _platform_direction,
    platform_line_id as _platform_line_id,
    vertical_direction as _vertical_direction,
)
from .design.schema import DesignElement, QueueSpec, StationDesignDocument
from .geometry_safety import (
    document_walkable_geometry,
    element_representative_point,
    element_walkable_domain,
    level_walkable_geometry,
    project_to_safe_point,
)


Point = tuple[float, float]


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    level_id: str
    position: Point
    kind: str
    element_id: str | None
    line_id: str | None = None
    direction: str | None = None
    facility_stage: str | None = None


@dataclass(frozen=True)
class GraphEdge:
    from_node: str
    to_node: str
    kind: str
    cost: float
    level_change: bool
    bidirectional: bool = False
    facility_stage: str | None = None


@dataclass(frozen=True)
class RouteSegment:
    node_ids: tuple[str, ...]
    positions: tuple[Point, ...]
    edges: tuple[GraphEdge, ...]


@dataclass(frozen=True)
class StationGraph:
    nodes: dict[str, GraphNode]
    edges: tuple[GraphEdge, ...]
    element_node_ids: dict[str, tuple[str, ...]]
    primary_node_by_element_id: dict[str, str]
    source_document: StationDesignDocument | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        adjacency: dict[str, list[GraphEdge]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            adjacency.setdefault(edge.from_node, []).append(edge)
        object.__setattr__(self, "_adjacency", adjacency)

    @classmethod
    def from_design(
        cls,
        document: StationDesignDocument,
        *,
        include_walkable_access_edges: bool = True,
    ) -> "StationGraph":
        nodes: dict[str, GraphNode] = {}
        element_node_ids: dict[str, list[str]] = {}
        primary_node_by_element_id: dict[str, str] = {}
        queues_by_owner = _queues_by_owner(document.queues)
        levels_by_id = document.level_by_id()
        elements_by_id = document.element_by_id()
        walkable_geometry = document_walkable_geometry(document)

        def add_node(node: GraphNode, *, primary: bool = False) -> None:
            nodes[node.node_id] = node
            if node.element_id is not None:
                element_node_ids.setdefault(node.element_id, []).append(node.node_id)
                if primary or node.element_id not in primary_node_by_element_id:
                    primary_node_by_element_id[node.element_id] = node.node_id

        for element in document.elements:
            queue = queues_by_owner.get(element.id)
            center = _element_node_position(element, walkable_geometry)
            if element.kind == "entrance":
                add_node(
                    GraphNode(
                        f"entrance:{element.id}", element.level_id, center, "entrance", element.id
                    ),
                    primary=True,
                )
            elif element.kind == "gate":
                service_point = queue.service_point_m if queue is not None else center
                gate_direction = _gate_direction(element)
                if gate_direction in {"entry", "bidirectional"}:
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:entry",
                            element.level_id,
                            service_point,
                            "facility_entry",
                            element.id,
                            facility_stage=FacilityStage.ENTRY_GATE.value,
                        )
                    )
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:paid",
                            element.level_id,
                            center,
                            "facility_exit",
                            element.id,
                            facility_stage=FacilityStage.ENTRY_GATE.value,
                        ),
                        primary=True,
                    )
                if gate_direction in {"exit", "bidirectional"}:
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:exit",
                            element.level_id,
                            center,
                            "facility_entry",
                            element.id,
                            facility_stage=FacilityStage.EXIT_GATE.value,
                        )
                    )
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:unpaid",
                            element.level_id,
                            service_point,
                            "facility_exit",
                            element.id,
                            facility_stage=FacilityStage.EXIT_GATE.value,
                        )
                    )
            elif element.role == "vertical_connector":
                for level_id in element.connects_levels:
                    position = _vertical_node_position(
                        element,
                        level_id,
                        levels_by_id,
                        walkable_geometry,
                    )
                    add_node(
                        GraphNode(
                            f"vertical:{element.id}:{level_id}",
                            level_id,
                            position,
                            "facility_entry",
                            element.id,
                            direction=_vertical_direction(element),
                            facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
                        ),
                        primary=level_id == element.level_id,
                    )
            elif element.kind == "platform_edge":
                line_id = _platform_line_id(element)
                direction = _platform_direction(element)
                add_node(
                    GraphNode(
                        f"platform:{element.id}",
                        element.level_id,
                        center,
                        "platform",
                        element.id,
                        line_id=line_id,
                        direction=direction,
                    ),
                    primary=True,
                )
            elif (
                (element.role == "floor" or element.kind == "walkable_area")
                and element.metadata.get("graph_node", True)
            ):
                add_node(
                    GraphNode(f"zone:{element.id}", element.level_id, center, "zone", element.id),
                    primary=True,
                )

        edges: list[GraphEdge] = []
        for element in document.elements:
            if element.kind == "gate":
                _add_gate_service_edges(edges, nodes, element)
            elif element.role == "vertical_connector":
                _add_vertical_service_edges(edges, nodes, element, levels_by_id)

        for connection in document.connections:
            source = elements_by_id.get(connection.source_id)
            target = elements_by_id.get(connection.target_id)
            if source is None or target is None:
                continue
            source_node = _connection_node_id(source, target, primary_node_by_element_id)
            target_node = _connection_node_id(target, source, primary_node_by_element_id)
            if source_node in nodes and target_node in nodes:
                edge_kind = "walk" if connection.kind == "vertical" else connection.kind
                _add_edge(
                    edges,
                    nodes,
                    source_node,
                    target_node,
                    kind=edge_kind,
                    bidirectional=connection.bidirectional,
                )

        if include_walkable_access_edges:
            _add_same_level_walkable_access_edges(edges, nodes, document, walkable_geometry)

        return cls(
            nodes=nodes,
            edges=tuple(edges),
            element_node_ids={key: tuple(value) for key, value in element_node_ids.items()},
            primary_node_by_element_id=primary_node_by_element_id,
            source_document=document,
        )

    def node_ids_for_element(self, element_id: str) -> tuple[str, ...]:
        return self.element_node_ids.get(element_id, ())

    def nodes_matching(
        self,
        *,
        kind: str | None = None,
        facility_stage: str | None = None,
        direction: str | tuple[str | None, ...] | None = None,
        line_id: str | None = None,
        level_id: str | None = None,
    ) -> list[GraphNode]:
        directions = None
        if isinstance(direction, tuple):
            directions = set(direction)
        elif direction is not None:
            directions = {direction}
        return [
            node
            for node in self.nodes.values()
            if (kind is None or node.kind == kind)
            and (facility_stage is None or node.facility_stage == facility_stage)
            and (directions is None or node.direction in directions)
            and (line_id is None or node.line_id == line_id)
            and (level_id is None or node.level_id == level_id)
        ]

    def nearest_node(
        self,
        position: Point,
        candidates: list[GraphNode] | None = None,
    ) -> GraphNode:
        pool = candidates or list(self.nodes.values())
        if not pool:
            raise ValueError("station graph has no nodes to route from")
        return min(pool, key=lambda node: _distance(position, node.position))

    def shortest_path(
        self,
        from_node: str,
        target_nodes: set[str],
        *,
        allowed_kinds: set[str] | None = None,
    ) -> RouteSegment | None:
        if from_node in target_nodes:
            node = self.nodes[from_node]
            return RouteSegment((from_node,), (node.position,), ())

        heap: list[tuple[float, str]] = [(0.0, from_node)]
        distances: dict[str, float] = {from_node: 0.0}
        previous: dict[str, tuple[str, GraphEdge]] = {}

        while heap:
            distance, node_id = heappop(heap)
            if distance > distances.get(node_id, float("inf")):
                continue
            if node_id in target_nodes:
                return self._reconstruct_path(from_node, node_id, previous)
            for edge in self._adjacency.get(node_id, []):
                if allowed_kinds is not None and edge.kind not in allowed_kinds:
                    continue
                new_distance = distance + edge.cost
                if new_distance < distances.get(edge.to_node, float("inf")):
                    distances[edge.to_node] = new_distance
                    previous[edge.to_node] = (node_id, edge)
                    heappush(heap, (new_distance, edge.to_node))
        return None

    def route_from_position_to(
        self,
        start: Point,
        *,
        kind: str,
        facility_stage: str | None = None,
        direction: str | tuple[str | None, ...] | None = None,
        line_id: str | None = None,
        start_level_id: str | None = None,
    ) -> tuple[Point, ...]:
        targets = self.nodes_matching(
            kind=kind,
            facility_stage=facility_stage,
            direction=direction,
            line_id=line_id,
        )
        if not targets:
            raise ValueError(
                f"No station graph nodes match kind={kind!r}, "
                f"facility_stage={facility_stage!r}, direction={direction!r}"
            )
        start_candidates = (
            self.nodes_matching(level_id=start_level_id) if start_level_id is not None else None
        )
        start_node = self.nearest_node(start, start_candidates)
        path = self.shortest_path(
            start_node.node_id,
            {node.node_id for node in targets},
            allowed_kinds={"walk"},
        )
        if path is None:
            raise ValueError(
                f"No station graph path from {start_node.node_id!r} to "
                f"kind={kind!r}, facility_stage={facility_stage!r}, "
                f"direction={direction!r}, line_id={line_id!r}"
            )
        positions = path.positions[1:] or path.positions
        return tuple(_dedupe_positions(positions))

    def facility_stages_on_path(self, node_ids: list[str]) -> list[str]:
        stages: list[str] = []
        pairs = zip(node_ids, node_ids[1:])
        for from_node, to_node in pairs:
            for edge in self._adjacency.get(from_node, []):
                if edge.to_node == to_node and edge.facility_stage is not None:
                    stages.append(edge.facility_stage)
                    break
        return stages

    def vertical_transfer_count_for_intent(self, intent: str | AgentIntent) -> int:
        if self.source_document is None:
            return 1

        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        elements = self.source_document.elements
        entrance_levels = [element.level_id for element in elements if element.kind == "entrance"]
        platform_levels = [
            element.level_id for element in elements if element.kind == "platform_edge"
        ]
        if not entrance_levels or not platform_levels:
            return 1

        levels_by_id = self.source_document.level_by_id()

        def level_distance(a: str, b: str) -> int:
            return abs(levels_by_id[a].order - levels_by_id[b].order)

        if intent_value in {AgentIntent.ENTER_AND_BOARD.value, AgentIntent.EXIT_STATION.value}:
            return min(
                level_distance(entrance_level, platform_level)
                for entrance_level in entrance_levels
                for platform_level in platform_levels
            )
        if len(set(platform_levels)) >= 2:
            return min(
                level_distance(a, b) for a in platform_levels for b in platform_levels if a != b
            )
        return 0

    def _reconstruct_path(
        self,
        from_node: str,
        to_node: str,
        previous: dict[str, tuple[str, GraphEdge]],
    ) -> RouteSegment:
        node_ids = [to_node]
        edges: list[GraphEdge] = []
        current = to_node
        while current != from_node:
            prior, edge = previous[current]
            node_ids.append(prior)
            edges.append(edge)
            current = prior
        node_ids.reverse()
        edges.reverse()
        return RouteSegment(
            node_ids=tuple(node_ids),
            positions=tuple(self.nodes[node_id].position for node_id in node_ids),
            edges=tuple(edges),
        )


def _queues_by_owner(queues: tuple[QueueSpec, ...]) -> dict[str, QueueSpec]:
    return {queue.owner_element_id: queue for queue in queues}


def _distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def _add_edge(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    from_node: str,
    to_node: str,
    *,
    kind: str,
    bidirectional: bool = False,
    facility_stage: str | None = None,
) -> None:
    source = nodes[from_node]
    target = nodes[to_node]
    cost = _distance(source.position, target.position)
    level_change = source.level_id != target.level_id
    edges.append(
        GraphEdge(from_node, to_node, kind, cost, level_change, bidirectional, facility_stage)
    )
    if bidirectional:
        edges.append(
            GraphEdge(to_node, from_node, kind, cost, level_change, bidirectional, facility_stage)
        )


def _add_gate_service_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    element: DesignElement,
) -> None:
    direction = _gate_direction(element)
    if direction in {"entry", "bidirectional"}:
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:entry",
            f"gate:{element.id}:paid",
            kind="service",
            facility_stage=FacilityStage.ENTRY_GATE.value,
        )
    if direction in {"exit", "bidirectional"}:
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:exit",
            f"gate:{element.id}:unpaid",
            kind="service",
            facility_stage=FacilityStage.EXIT_GATE.value,
        )
    if direction == "bidirectional":
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:unpaid",
            f"gate:{element.id}:entry",
            kind="walk",
            bidirectional=True,
        )
        _add_edge(
            edges,
            nodes,
            f"gate:{element.id}:paid",
            f"gate:{element.id}:exit",
            kind="walk",
            bidirectional=True,
        )


def _add_vertical_service_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    element: DesignElement,
    levels_by_id: dict[str, Any],
) -> None:
    ordered_levels = sorted(
        element.connects_levels,
        key=lambda level_id: levels_by_id[level_id].elevation_m,
        reverse=True,
    )
    direction = _vertical_direction(element)
    for upper, lower in zip(ordered_levels, ordered_levels[1:]):
        upper_node = f"vertical:{element.id}:{upper}"
        lower_node = f"vertical:{element.id}:{lower}"
        if direction in {"down", "both"}:
            _add_edge(
                edges,
                nodes,
                upper_node,
                lower_node,
                kind="vertical",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
            )
        if direction in {"up", "both"}:
            _add_edge(
                edges,
                nodes,
                lower_node,
                upper_node,
                kind="vertical",
                facility_stage=FacilityStage.VERTICAL_TRANSFER.value,
            )


def _add_same_level_walkable_access_edges(
    edges: list[GraphEdge],
    nodes: dict[str, GraphNode],
    document: StationDesignDocument,
    walkable_geometry,
) -> None:
    """Connect physical access points to their same-level walkable floor.

    Explicit design connections still define the station process graph. This
    pass prevents valid physical endpoints, especially vertical-connector ends,
    from becoming graph islands when they are already inside the same walkable
    floor component.
    """

    edge_pairs = {(edge.from_node, edge.to_node) for edge in edges if edge.kind == "walk"}

    def add_walk_edge(from_node: str, to_node: str) -> None:
        if from_node == to_node or (from_node, to_node) in edge_pairs:
            return
        _add_edge(edges, nodes, from_node, to_node, kind="walk", bidirectional=True)
        edge_pairs.add((from_node, to_node))
        edge_pairs.add((to_node, from_node))

    for level in document.levels:
        level_nodes = [node for node in nodes.values() if node.level_id == level.id]
        zone_nodes = [node for node in level_nodes if node.kind == "zone"]
        if not zone_nodes:
            continue

        level_domain = level_walkable_geometry(document, level.id, walkable_geometry)
        for node in level_nodes:
            if not _needs_same_level_floor_access(node):
                continue
            candidates = [
                zone
                for zone in zone_nodes
                if _same_level_walk_segment_supported(level_domain, node.position, zone.position)
            ]
            if not candidates:
                candidates = zone_nodes
            nearest = min(candidates, key=lambda zone: _distance(node.position, zone.position))
            add_walk_edge(node.node_id, nearest.node_id)

        for left in zone_nodes:
            candidates = [
                right
                for right in zone_nodes
                if right.node_id != left.node_id
                and _same_level_walk_segment_supported(level_domain, left.position, right.position)
            ]
            if candidates:
                nearest = min(
                    candidates, key=lambda right: _distance(left.position, right.position)
                )
                add_walk_edge(left.node_id, nearest.node_id)


def _needs_same_level_floor_access(node: GraphNode) -> bool:
    if node.kind in {"entrance", "platform"}:
        return True
    if node.kind == "facility_exit":
        return True
    return (
        node.kind in {"facility_entry", "facility_exit"}
        and node.facility_stage == FacilityStage.VERTICAL_TRANSFER.value
    )


def _same_level_walk_segment_supported(level_domain, start: Point, end: Point) -> bool:
    if level_domain.is_empty:
        return False
    segment = LineString((start, end))
    if segment.length <= 0.001:
        return True
    return level_domain.buffer(0.05).covers(segment)


def _connection_node_id(
    element: DesignElement,
    other: DesignElement,
    primary_node_by_element_id: dict[str, str],
) -> str:
    if element.kind == "gate":
        direction = _gate_direction(element)
        if other.kind == "entrance" and direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:entry"
        if direction in {"entry", "bidirectional"}:
            return f"gate:{element.id}:paid"
        if direction == "exit":
            return f"gate:{element.id}:exit"
    if element.role == "vertical_connector":
        if other.level_id in element.connects_levels:
            return f"vertical:{element.id}:{other.level_id}"
    return primary_node_by_element_id[element.id]


def _vertical_node_position(
    element: DesignElement,
    level_id: str,
    levels_by_id: dict[str, Any],
    walkable_geometry,
) -> Point:
    if element.geometry.shape == "polyline" and element.geometry.points_m:
        ordered_levels = sorted(
            element.connects_levels,
            key=lambda item: levels_by_id[item].elevation_m,
            reverse=True,
        )
        level_index = max(0, ordered_levels.index(level_id))
        point_index = round(
            level_index * (len(element.geometry.points_m) - 1) / max(1, len(ordered_levels) - 1)
        )
        raw = element.geometry.points_m[point_index]
    else:
        raw = element.geometry.center()
    return project_to_safe_point(walkable_geometry, raw, clearance=0.18, require_inside=False)


def _element_node_position(element: DesignElement, walkable_geometry) -> Point:
    domain = element_walkable_domain(element, walkable_geometry)
    raw = element_representative_point(element.geometry)
    return project_to_safe_point(domain, raw, clearance=0.18, require_inside=False)


def _dedupe_positions(points: tuple[Point, ...]) -> list[Point]:
    deduped: list[Point] = []
    for point in points:
        if not deduped or _distance(deduped[-1], point) > 0.001:
            deduped.append(point)
    return deduped
