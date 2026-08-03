from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush


from ..planning.plan import AgentIntent, FacilityStage
from ..design.helpers import (
    gate_direction as _gate_direction,
    platform_direction as _platform_direction,
    platform_line_id as _platform_line_id,
    vertical_direction as _vertical_direction,
)
from ..design.schema import (
    StationDesignDocument,
)
from .geometry import (
    document_walkable_geometry,
    level_walkable_geometry,
    project_to_safe_point,
)


from .graph_compilation import (
    _add_edge,
    _add_gate_service_edges,
    _add_same_level_walkable_access_edges,
    _add_vertical_service_edges,
    _connection_node_id_for_connection,
    _dedupe_positions,
    _distance,
    _element_node_position,
    _queues_by_owner,
    _vertical_node_position,
)
from .graph_types import (
    GraphCompileDiagnostic,
    GraphEdge,
    GraphNode,
    Point,
    RouteSegment,
)


@dataclass(frozen=True)
class StationGraph:
    nodes: dict[str, GraphNode]
    edges: tuple[GraphEdge, ...]
    element_node_ids: dict[str, tuple[str, ...]]
    primary_node_by_element_id: dict[str, str]
    compile_diagnostics: tuple[GraphCompileDiagnostic, ...] = field(
        default=(),
        compare=False,
        repr=False,
    )
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
        diagnostics: list[GraphCompileDiagnostic] = []

        def add_node(node: GraphNode, *, primary: bool = False) -> None:
            nodes[node.node_id] = node
            if node.element_id is not None:
                element_node_ids.setdefault(node.element_id, []).append(node.node_id)
                if primary or node.element_id not in primary_node_by_element_id:
                    primary_node_by_element_id[node.element_id] = node.node_id

        for element in document.elements:
            queue = queues_by_owner.get(element.id)
            element_level_domain = level_walkable_geometry(
                document,
                element.level_id,
                walkable_geometry,
            )
            center = _element_node_position(element, element_level_domain)
            if element.kind == "entrance":
                add_node(
                    GraphNode(
                        f"entrance:{element.id}",
                        element.level_id,
                        center,
                        "entrance",
                        element.id,
                        tactical_anchor=True,
                    ),
                    primary=True,
                )
            elif element.kind == "gate":
                service_point = project_to_safe_point(
                    element_level_domain,
                    queue.service_point_m if queue is not None else center,
                    clearance=0.18,
                    require_inside=False,
                )
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
                            tactical_anchor=True,
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
                            tactical_anchor=True,
                        ),
                        primary=True,
                    )
                if gate_direction in {"exit", "bidirectional"}:
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:exit",
                            element.level_id,
                            service_point,
                            "facility_entry",
                            element.id,
                            facility_stage=FacilityStage.EXIT_GATE.value,
                            tactical_anchor=True,
                        )
                    )
                    add_node(
                        GraphNode(
                            f"gate:{element.id}:unpaid",
                            element.level_id,
                            center,
                            "facility_exit",
                            element.id,
                            facility_stage=FacilityStage.EXIT_GATE.value,
                            tactical_anchor=True,
                        )
                    )
            elif element.role == "vertical_connector":
                for level_id in element.connects_levels:
                    position = _vertical_node_position(
                        element,
                        level_id,
                        levels_by_id,
                        document,
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
                            tactical_anchor=True,
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
                        tactical_anchor=True,
                    ),
                    primary=True,
                )
            elif (
                element.role == "floor" or element.kind == "walkable_area"
            ) and element.metadata.get("graph_node", True):
                add_node(
                    GraphNode(
                        f"zone:{element.id}",
                        element.level_id,
                        center,
                        "zone",
                        element.id,
                        tactical_anchor=bool(element.metadata.get("tactical_anchor", False)),
                    ),
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
            source_node = _connection_node_id_for_connection(
                connection,
                source,
                target,
                "source",
                primary_node_by_element_id,
                diagnostics,
            )
            target_node = _connection_node_id_for_connection(
                connection,
                target,
                source,
                "target",
                primary_node_by_element_id,
                diagnostics,
            )
            if source_node in nodes and target_node in nodes:
                edge_kind = "walk" if connection.kind == "vertical" else connection.kind
                _add_edge(
                    edges,
                    nodes,
                    source_node,
                    target_node,
                    kind=edge_kind,
                    bidirectional=connection.bidirectional,
                    origin="design_connection",
                    detail_id=connection.id,
                )
            else:
                diagnostics.append(
                    GraphCompileDiagnostic(
                        "error",
                        "graph.connection_node_missing",
                        f"{connection.id} could not resolve graph nodes for "
                        f"{connection.source_id}->{connection.target_id}",
                        connection_id=connection.id,
                        metadata={
                            "source_node": source_node,
                            "target_node": target_node,
                        },
                    )
                )

        if include_walkable_access_edges:
            _add_same_level_walkable_access_edges(
                edges,
                nodes,
                document,
                walkable_geometry,
                diagnostics,
            )

        return cls(
            nodes=nodes,
            edges=tuple(edges),
            element_node_ids={key: tuple(value) for key, value in element_node_ids.items()},
            primary_node_by_element_id=primary_node_by_element_id,
            compile_diagnostics=tuple(diagnostics),
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

    def edge_between(
        self,
        from_node: str,
        to_node: str,
        *,
        kind: str | None = None,
    ) -> GraphEdge | None:
        return next(
            (
                edge
                for edge in self._adjacency.get(from_node, ())
                if edge.to_node == to_node and (kind is None or edge.kind == kind)
            ),
            None,
        )

    def can_start_same_level_walk(self, node_id: str) -> bool:
        """Return whether a graph node can seed a same-level walking route.

        A directed facility approach portal can intentionally be a walking
        sink.  Snapping a replanning passenger to such a portal would erase
        their real freedom to walk away through the surrounding floor and
        make every routing algorithm report a false ``route_not_found``.
        """

        return any(
            edge.kind == "walk" and not edge.level_change
            for edge in self._adjacency.get(node_id, ())
        )

    def same_level_walk_neighbor_positions(self, node_id: str) -> tuple[Point, ...]:
        """Return physically connected egress anchors ordered by edge cost."""

        neighbors = [
            (float(edge.cost), edge.to_node, self.nodes[edge.to_node].position)
            for edge in self._adjacency.get(node_id, ())
            if edge.kind == "walk"
            and not edge.level_change
            and edge.to_node in self.nodes
        ]
        neighbors.sort(key=lambda item: (item[0], item[1]))
        return tuple(position for _cost, _node_id, position in neighbors)

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
        start_kind: str | None = None,
        start_facility_stage: str | None = None,
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
        start_candidates = None
        if start_level_id is not None or start_kind is not None or start_facility_stage is not None:
            start_candidates = [
                node
                for node in self.nodes.values()
                if (start_level_id is None or node.level_id == start_level_id)
                and (start_kind is None or node.kind == start_kind)
                and (start_facility_stage is None or node.facility_stage == start_facility_stage)
            ]
            if not start_candidates:
                raise ValueError(
                    f"No station graph start nodes match level={start_level_id!r}, "
                    f"kind={start_kind!r}, facility_stage={start_facility_stage!r}"
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

        if intent_value in {
            AgentIntent.ENTER_AND_BOARD.value,
            AgentIntent.EXIT_STATION.value,
            AgentIntent.EVACUATE_STATION.value,
        }:
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
