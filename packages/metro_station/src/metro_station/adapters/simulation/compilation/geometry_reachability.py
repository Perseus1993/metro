from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from math import hypot
from threading import RLock
from typing import Any

from shapely import from_wkb
from shapely.geometry import LineString, Point as ShapelyPoint

from ..design.schema import StationDesignDocument
from ..design.vertical_landing import vertical_landing_position
from ..design.validation_issue import ValidationIssue, issue
from ..movement.waypoint_policy import tactical_route_clearance
from ..station.geometry import element_representative_point, level_walkable_geometry
from ..station.graph import StationGraph
from ..station.graph_types import GraphEdge, Point


MAX_DETOUR_RATIO = 3.0
DEFAULT_AGENT_RADIUS_M = 0.18
_DOMAIN_TOLERANCE_M = 1e-6


class GeometryRoutingEngineBuildError(RuntimeError):
    """The compiler could not construct the runtime-equivalent navmesh."""


@dataclass(frozen=True)
class GeometryCompilePolicy:
    agent_radius_m: float = DEFAULT_AGENT_RADIUS_M
    max_detour_ratio: float = MAX_DETOUR_RATIO
    target_radius_m: float = 0.45
    personal_space_m: float = 0.8
    clearance_multiplier: float = 2.2
    gate_lane_edge_inset_m: float = 0.45
    gate_queue_slots_per_row: int = 22
    vertical_queue_slots_per_row: int = 18
    boarding_queue_slots_per_row: int = 18

    def __post_init__(self) -> None:
        if self.agent_radius_m <= 0.0:
            raise ValueError("geometry compile agent_radius_m must be positive")
        if self.max_detour_ratio <= 1.0:
            raise ValueError("geometry compile max_detour_ratio must exceed 1.0")
        for name in (
            "target_radius_m",
            "personal_space_m",
            "clearance_multiplier",
        ):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"geometry compile {name} must be positive")
        if self.gate_lane_edge_inset_m < 0.0:
            raise ValueError("geometry compile gate_lane_edge_inset_m cannot be negative")
        for name in (
            "gate_queue_slots_per_row",
            "vertical_queue_slots_per_row",
            "boarding_queue_slots_per_row",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"geometry compile {name} must be positive")

    @property
    def two_body_clearance_m(self) -> float:
        return max(
            self.agent_radius_m * 2.0,
            self.agent_radius_m * self.clearance_multiplier,
        )

    @classmethod
    def from_scenario(cls, scenario: Any) -> "GeometryCompilePolicy":
        return cls(
            agent_radius_m=float(scenario.jupedsim_agent_radius_units),
            target_radius_m=float(scenario.jupedsim_target_radius_units),
            personal_space_m=float(getattr(scenario, "personal_space_units", 0.8)),
            clearance_multiplier=float(scenario.jupedsim_clearance_multiplier),
            gate_lane_edge_inset_m=float(scenario.gate_lane_edge_inset_max),
            gate_queue_slots_per_row=int(scenario.gate_queue_slots_per_row),
            vertical_queue_slots_per_row=int(scenario.vertical_queue_slots_per_row),
            boarding_queue_slots_per_row=int(scenario.boarding_queue_slots_per_row),
        )


@dataclass(frozen=True)
class WalkEdgeRoute:
    edge: GraphEdge
    source_position: Point
    target_position: Point
    waypoints: tuple[Point, ...] | None
    failure_code: str | None = None


class _RoutingEngineCache:
    """Small bounded cache keyed by level and exact walkable-domain WKB."""

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max_size
        self._items: OrderedDict[tuple[str, bytes], Any] = OrderedDict()
        self._lock = RLock()

    def get(self, level_id: str, domain: Any) -> Any:
        key = level_id, bytes(domain.wkb)
        with self._lock:
            engine = self._items.get(key)
            if engine is not None:
                self._items.move_to_end(key)
                return engine
        try:
            import jupedsim as jps

            engine = jps.RoutingEngine(from_wkb(key[1]))
        except Exception as exc:  # pragma: no cover - exact exception is jps-version specific
            raise GeometryRoutingEngineBuildError(
                f"navigation mesh build failed for level {level_id!r}"
            ) from exc
        with self._lock:
            self._items[key] = engine
            self._items.move_to_end(key)
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)
        return engine


_ROUTING_ENGINES = _RoutingEngineCache()


def validate_geometry_reachability(
    document: StationDesignDocument,
    *,
    graph: StationGraph | None = None,
    policy: GeometryCompilePolicy | None = None,
) -> list[ValidationIssue]:
    """Validate semantic walk edges against each level's continuous domain.

    The station graph says which endpoints may be connected.  This validator
    proves that the corresponding endpoints are connected by the same JuPedSim
    navigation mesh used at runtime; graph reachability alone is insufficient.
    """

    station_graph = graph or StationGraph.from_design(
        document,
        include_walkable_access_edges=False,
    )
    compile_policy = policy or GeometryCompilePolicy()
    navigation_clearance = tactical_route_clearance(
        agent_radius=compile_policy.agent_radius_m,
        final_target_radius=compile_policy.target_radius_m,
    )
    raw_domains = {
        level.id: level_walkable_geometry(document, level.id)
        for level in document.levels
    }
    domains = {
        level_id: domain.buffer(
            -navigation_clearance,
            join_style="mitre",
        )
        for level_id, domain in raw_domains.items()
    }
    issues: list[ValidationIssue] = []
    invalid_levels = {
        level_id
        for level_id, domain in domains.items()
        if not _is_polygonal_domain(raw_domains[level_id])
        or not _is_polygonal_domain(domain)
    }
    for level_id in sorted(invalid_levels):
        domain = domains[level_id]
        issues.append(
            issue(
                "error",
                "geometry.level_domain_disconnected",
                f"levels.{level_id}",
                f"level {level_id!r} has no usable polygonal walkable domain; "
                f"compiled geometry is {domain.geom_type}",
            )
        )
    routes: list[WalkEdgeRoute] = []
    routed_connections: dict[tuple[str, str, str, str], WalkEdgeRoute] = {}
    disconnected_level_reported: set[str] = set()

    for edge in station_graph.edges:
        if edge.kind != "walk" or edge.level_change:
            continue
        from_node, to_node = sorted((edge.from_node, edge.to_node))
        connection_key = (
            from_node,
            to_node,
            str(edge.origin),
            str(edge.detail_id or ""),
        )
        routed = routed_connections.get(connection_key)
        if routed is None:
            source_level = station_graph.nodes[edge.from_node].level_id
            if source_level in invalid_levels:
                # The level-level diagnostic is the root cause.  Suppress one
                # error per incident edge so disconnected domains cannot flood
                # reports with misleading cascades.
                continue
            routed = _route_walk_edge(
                document,
                station_graph,
                edge,
                domains,
                navigation_clearance,
            )
            routed_connections[connection_key] = routed
            routes.append(routed)
            edge_issue = _route_issue(station_graph, routed)
            if edge_issue is not None:
                source_level = station_graph.nodes[edge.from_node].level_id
                if (
                    edge_issue.code != "geometry.level_domain_disconnected"
                    or source_level not in disconnected_level_reported
                ):
                    issues.append(edge_issue)
                    if edge_issue.code == "geometry.level_domain_disconnected":
                        disconnected_level_reported.add(source_level)
            detour_issue = _detour_issue(
                station_graph,
                routed,
                max_detour_ratio=compile_policy.max_detour_ratio,
            )
            if detour_issue is not None:
                issues.append(detour_issue)

    successful_pairs = {
        tuple(sorted((routed.edge.from_node, routed.edge.to_node)))
        for routed in routes
        if routed.failure_code is None
    }
    failed_pairs = {
        tuple(sorted((routed.edge.from_node, routed.edge.to_node)))
        for routed in routes
        if routed.failure_code is not None
    } - successful_pairs
    # A crossed disconnected component is already the level-scoped root cause;
    # adding one entrance error per downstream route would only be a cascade.
    if not invalid_levels and not disconnected_level_reported:
        issues.extend(_entrance_platform_issues(station_graph, failed_pairs))
    return issues


def _route_walk_edge(
    document: StationDesignDocument,
    graph: StationGraph,
    edge: GraphEdge,
    domains: dict[str, Any],
    agent_radius: float,
) -> WalkEdgeRoute:
    source = graph.nodes[edge.from_node]
    source_position, target_position = _semantic_edge_endpoints(
        document,
        graph,
        edge,
        agent_radius=agent_radius,
    )
    domain = domains.get(source.level_id)
    if domain is None or domain.is_empty:
        return WalkEdgeRoute(
            edge,
            source_position,
            target_position,
            None,
            "geometry.walk_edge_not_traversable",
        )

    navigation_domain = domain
    source_point = ShapelyPoint(source_position)
    target_point = ShapelyPoint(target_position)
    buffered = navigation_domain.buffer(_DOMAIN_TOLERANCE_M)
    if not buffered.covers(source_point) or not buffered.covers(target_point):
        return WalkEdgeRoute(
            edge,
            source_position,
            target_position,
            None,
            "geometry.walk_edge_not_traversable",
        )

    component = _component_for_pair(navigation_domain, source_point, target_point)
    if component is None:
        return WalkEdgeRoute(
            edge,
            source_position,
            target_position,
            None,
            (
                "geometry.level_domain_disconnected"
                if navigation_domain.geom_type == "MultiPolygon"
                else "geometry.walk_edge_not_traversable"
            ),
        )

    if hypot(
        source_position[0] - target_position[0],
        source_position[1] - target_position[1],
    ) <= 0.001:
        return WalkEdgeRoute(edge, source_position, target_position, (source_position, target_position))

    try:
        # GEOS negative buffers and JuPedSim's point classifier disagree at
        # sub-micrometre boundary noise.  This numerical skin is far below any
        # physical tolerance and prevents an exactly radius-clear compiler
        # anchor from being rejected as outside.
        routing_component = component.buffer(_DOMAIN_TOLERANCE_M)
        engine = _ROUTING_ENGINES.get(source.level_id, routing_component)
        waypoints = tuple(
            (float(point[0]), float(point[1]))
            for point in engine.compute_waypoints(source_position, target_position)
        )
    except GeometryRoutingEngineBuildError:
        raise
    except Exception:
        return WalkEdgeRoute(
            edge,
            source_position,
            target_position,
            None,
            "geometry.walk_edge_not_traversable",
        )
    if not waypoints or not _route_stays_in_domain(component, waypoints):
        return WalkEdgeRoute(
            edge,
            source_position,
            target_position,
            None,
            "geometry.walk_edge_not_traversable",
        )
    return WalkEdgeRoute(edge, source_position, target_position, waypoints)


def _is_polygonal_domain(domain: Any) -> bool:
    return not domain.is_empty and domain.geom_type in {"Polygon", "MultiPolygon"}


def _semantic_edge_endpoints(
    document: StationDesignDocument,
    graph: StationGraph,
    edge: GraphEdge,
    *,
    agent_radius: float,
) -> tuple[Point, Point]:
    connection = next(
        (item for item in document.connections if item.id == edge.detail_id),
        None,
    )
    source = _semantic_node_position(
        document,
        graph,
        edge.from_node,
        agent_radius=agent_radius,
    )
    target = _semantic_node_position(
        document,
        graph,
        edge.to_node,
        agent_radius=agent_radius,
    )
    if connection is None:
        return source, target
    elements = document.element_by_id()
    if edge.from_node in graph.element_node_ids.get(connection.source_id, ()):
        source = _authored_endpoint(elements.get(connection.source_id), connection.source_port_id, source)
        target = _authored_endpoint(elements.get(connection.target_id), connection.target_port_id, target)
    else:
        source = _authored_endpoint(elements.get(connection.target_id), connection.target_port_id, source)
        target = _authored_endpoint(elements.get(connection.source_id), connection.source_port_id, target)
    return source, target


def _authored_endpoint(element: Any, port_id: str | None, fallback: Point) -> Point:
    if element is None or port_id is None:
        return fallback
    port = next((item for item in element.ports if item.id == port_id), None)
    if port is None or port.position_m is None:
        return fallback
    return float(port.position_m[0]), float(port.position_m[1])


def _semantic_node_position(
    document: StationDesignDocument,
    graph: StationGraph,
    node_id: str,
    *,
    agent_radius: float,
) -> Point:
    node = graph.nodes[node_id]
    if node.element_id is None:
        return node.position
    element = document.element_by_id().get(node.element_id)
    if element is None:
        return node.position
    if element.kind == "walkable_area" or element.role == "floor":
        # A floor/zone node is a compiler-derived tactical anchor, not an
        # authored portal.  Its representative point is intentionally chosen
        # from the obstacle-subtracted element domain.
        return node.position
    if element.role == "vertical_connector":
        return vertical_landing_position(
            element,
            node.level_id,
            document.level_by_id(),
            walkable_geometry=None,
            clearance=agent_radius,
        )
    if element.kind == "gate" and node.kind == "facility_entry":
        queue = next(
            (item for item in document.queues if item.owner_element_id == element.id),
            None,
        )
        if queue is not None:
            return float(queue.service_point_m[0]), float(queue.service_point_m[1])
    return element_representative_point(element.geometry)


def _component_for_pair(domain: Any, source: Any, target: Any) -> Any | None:
    components = tuple(getattr(domain, "geoms", (domain,)))
    for component in components:
        buffered = component.buffer(_DOMAIN_TOLERANCE_M)
        if buffered.covers(source) and buffered.covers(target):
            return component
    return None


def _route_stays_in_domain(domain: Any, waypoints: tuple[Point, ...]) -> bool:
    if len(waypoints) == 1:
        return domain.buffer(_DOMAIN_TOLERANCE_M).covers(ShapelyPoint(waypoints[0]))
    return domain.buffer(_DOMAIN_TOLERANCE_M).covers(LineString(waypoints))


def _route_issue(graph: StationGraph, routed: WalkEdgeRoute) -> ValidationIssue | None:
    if routed.failure_code is None:
        return None
    edge = routed.edge
    source = graph.nodes[edge.from_node]
    detail = edge.detail_id or f"{edge.from_node}->{edge.to_node}"
    if routed.failure_code == "geometry.level_domain_disconnected":
        message = (
            f"walk edge {detail!r} crosses disconnected components of level "
            f"{source.level_id!r}: {routed.source_position!r} -> {routed.target_position!r}"
        )
    else:
        message = (
            f"walk edge {detail!r} has no continuous JuPedSim route on level "
            f"{source.level_id!r}: {routed.source_position!r} -> {routed.target_position!r}"
        )
    return issue("error", routed.failure_code, f"connections.{detail}", message)


def _detour_issue(
    graph: StationGraph,
    routed: WalkEdgeRoute,
    *,
    max_detour_ratio: float,
) -> ValidationIssue | None:
    if routed.waypoints is None:
        return None
    edge = routed.edge
    direct = hypot(
        routed.source_position[0] - routed.target_position[0],
        routed.source_position[1] - routed.target_position[1],
    )
    if direct <= 0.001:
        return None
    path_length = sum(
        hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(routed.waypoints, routed.waypoints[1:], strict=False)
    )
    ratio = path_length / direct
    if ratio <= max_detour_ratio:
        return None
    detail = edge.detail_id or f"{edge.from_node}->{edge.to_node}"
    return issue(
        "warning",
        "geometry.detour_ratio_exceeded",
        f"connections.{detail}",
        f"walk edge {detail!r} detour ratio {ratio:.3f} exceeds {max_detour_ratio:.1f}",
    )


def _entrance_platform_issues(
    graph: StationGraph,
    failed_walk_pairs: set[tuple[str, str]],
) -> list[ValidationIssue]:
    platform_ids = {node.node_id for node in graph.nodes_matching(kind="platform")}
    if not platform_ids:
        return []
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in graph.nodes}
    for edge in graph.edges:
        if edge.kind == "walk" and tuple(sorted((edge.from_node, edge.to_node))) in failed_walk_pairs:
            continue
        adjacency.setdefault(edge.from_node, []).append(edge.to_node)

    issues: list[ValidationIssue] = []
    for entrance in graph.nodes_matching(kind="entrance"):
        # Graph topology owns missing semantic routes.  This diagnostic is
        # specifically for a route that exists semantically but becomes
        # impossible after failed continuous-space walk edges are removed.
        if graph.shortest_path(entrance.node_id, platform_ids) is None:
            continue
        if _reaches_any(adjacency, entrance.node_id, platform_ids):
            continue
        issues.append(
            issue(
                "error",
                "geometry.entrance_platform_unreachable",
                f"elements.{entrance.element_id or entrance.node_id}",
                f"entrance {entrance.node_id!r} has no continuous-space route to any platform",
            )
        )
    return issues


def _reaches_any(adjacency: dict[str, list[str]], start: str, targets: set[str]) -> bool:
    seen: set[str] = set()
    pending: deque[str] = deque((start,))
    while pending:
        node_id = pending.popleft()
        if node_id in seen:
            continue
        if node_id in targets:
            return True
        seen.add(node_id)
        pending.extend(next_id for next_id in adjacency.get(node_id, ()) if next_id not in seen)
    return False


__all__ = [
    "DEFAULT_AGENT_RADIUS_M",
    "GeometryCompilePolicy",
    "GeometryRoutingEngineBuildError",
    "MAX_DETOUR_RATIO",
    "validate_geometry_reachability",
]
