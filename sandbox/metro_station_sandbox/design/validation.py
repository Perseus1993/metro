from __future__ import annotations

from dataclasses import dataclass

from .schema import DesignElement, StationDesignDocument


PORT_KINDS = {
    "walk",
    "queue",
    "service",
    "release",
    "vertical",
    "platform",
    "fare_unpaid",
    "fare_paid",
}
PORT_DIRECTIONS = {"in", "out", "bidirectional"}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def validate_design(document: StationDesignDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = document.constraints

    if document.units != "meters":
        issues.append(_issue("error", "units.unsupported", "units", "design units must be meters"))

    if len(document.levels) > constraints.max_levels:
        issues.append(
            _issue(
                "error",
                "levels.too_many",
                "levels",
                f"{len(document.levels)} levels exceed max_levels={constraints.max_levels}",
            )
        )

    level_ids = [level.id for level in document.levels]
    duplicate_levels = _duplicates(level_ids)
    for level_id in duplicate_levels:
        issues.append(
            _issue("error", "levels.duplicate_id", "levels", f"duplicate level id {level_id!r}")
        )

    for index, level in enumerate(document.levels):
        path = f"levels[{index}]"
        if level.elevation_m < -constraints.max_depth_m:
            issues.append(
                _issue(
                    "error",
                    "levels.depth_exceeded",
                    f"{path}.elevation_m",
                    f"{level.id} elevation {level.elevation_m}m exceeds max_depth_m={constraints.max_depth_m}",
                )
            )
        if (
            not constraints.min_floor_height_m
            <= level.floor_to_floor_height_m
            <= constraints.max_floor_height_m
        ):
            issues.append(
                _issue(
                    "error",
                    "levels.floor_height_out_of_range",
                    f"{path}.floor_to_floor_height_m",
                    f"{level.id} floor height {level.floor_to_floor_height_m}m is outside "
                    f"{constraints.min_floor_height_m}-{constraints.max_floor_height_m}m",
                )
            )
        issues.extend(_validate_points(level.footprint, f"{path}.footprint", document))

    sorted_levels = sorted(document.levels, key=lambda item: item.elevation_m, reverse=True)
    for upper, lower in zip(sorted_levels, sorted_levels[1:]):
        spacing = abs(upper.elevation_m - lower.elevation_m)
        if not constraints.min_floor_height_m <= spacing <= constraints.max_floor_height_m:
            issues.append(
                _issue(
                    "warning",
                    "levels.spacing_out_of_range",
                    f"levels.{upper.id}->{lower.id}",
                    f"vertical spacing {spacing}m is outside "
                    f"{constraints.min_floor_height_m}-{constraints.max_floor_height_m}m",
                )
            )

    element_ids = [element.id for element in document.elements]
    for element_id in _duplicates(element_ids):
        issues.append(
            _issue(
                "error", "elements.duplicate_id", "elements", f"duplicate element id {element_id!r}"
            )
        )

    known_levels = set(level_ids)
    allowed_facilities = set(constraints.allowed_facility_kinds)
    known_elements = set(element_ids)
    elements_by_id = document.element_by_id()

    for index, element in enumerate(document.elements):
        path = f"elements[{index}]"
        if element.level_id not in known_levels:
            issues.append(
                _issue(
                    "error",
                    "elements.unknown_level",
                    f"{path}.level_id",
                    f"{element.id} references unknown level {element.level_id!r}",
                )
            )
        if (
            element.role != "floor"
            and element.kind not in allowed_facilities
            and element.kind != "platform_edge"
        ):
            issues.append(
                _issue(
                    "error",
                    "elements.kind_not_allowed",
                    f"{path}.kind",
                    f"{element.kind!r} is not allowed by constraints",
                )
            )
        issues.extend(_validate_geometry(element.geometry, f"{path}.geometry", document))
        issues.extend(_validate_element_ports(element, path, known_levels, document))
        if element.kind == "gate":
            if element.gate_direction not in {"entry", "exit", "bidirectional"}:
                issues.append(
                    _issue(
                        "error",
                        "gates.invalid_direction",
                        f"{path}.gate_direction",
                        f"{element.id} gate_direction must be entry, exit, or bidirectional",
                    )
                )
        if element.role == "vertical_connector":
            if len(element.connects_levels) < 2:
                issues.append(
                    _issue(
                        "error",
                        "connectors.missing_levels",
                        f"{path}.connects_levels",
                        f"{element.id} must connect at least two levels",
                    )
                )
            for level_id in element.connects_levels:
                if level_id not in known_levels:
                    issues.append(
                        _issue(
                            "error",
                            "connectors.unknown_level",
                            f"{path}.connects_levels",
                            f"{element.id} connects unknown level {level_id!r}",
                        )
                    )
            if element.direction not in {"up", "down", "both"}:
                issues.append(
                    _issue(
                        "error",
                        "connectors.invalid_direction",
                        f"{path}.direction",
                        f"{element.id} direction must be up, down, or both",
                    )
                )
        if element.kind == "platform_edge":
            if not element.line_id:
                issues.append(
                    _issue(
                        "error",
                        "platform.missing_line_id",
                        f"{path}.line_id",
                        f"{element.id} must declare line_id",
                    )
                )
            if element.direction not in {"up", "down"}:
                issues.append(
                    _issue(
                        "error",
                        "platform.invalid_direction",
                        f"{path}.direction",
                        f"{element.id} direction must be up or down",
                    )
                )
        if element.capacity is not None and element.capacity <= 0:
            issues.append(
                _issue(
                    "error",
                    "elements.invalid_capacity",
                    f"{path}.capacity",
                    f"{element.id} capacity must be positive",
                )
            )

    queue_ids = [queue.id for queue in document.queues]
    for queue_id in _duplicates(queue_ids):
        issues.append(
            _issue("error", "queues.duplicate_id", "queues", f"duplicate queue id {queue_id!r}")
        )

    for index, queue in enumerate(document.queues):
        path = f"queues[{index}]"
        if queue.owner_element_id not in known_elements:
            issues.append(
                _issue(
                    "error",
                    "queues.unknown_owner",
                    f"{path}.owner_element_id",
                    f"{queue.id} references unknown element {queue.owner_element_id!r}",
                )
            )
        if queue.level_id not in known_levels:
            issues.append(
                _issue(
                    "error",
                    "queues.unknown_level",
                    f"{path}.level_id",
                    f"{queue.id} references unknown level {queue.level_id!r}",
                )
            )
        if queue.capacity <= 0:
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_capacity",
                    f"{path}.capacity",
                    f"{queue.id} capacity must be positive",
                )
            )
        if queue.spacing_m <= 0:
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_spacing",
                    f"{path}.spacing_m",
                    f"{queue.id} spacing must be positive",
                )
            )
        issues.extend(_validate_geometry(queue.geometry, f"{path}.geometry", document))
        issues.extend(
            _validate_points((queue.service_point_m,), f"{path}.service_point_m", document)
        )

    for index, connection in enumerate(document.connections):
        path = f"connections[{index}]"
        if connection.source_id not in known_elements:
            issues.append(
                _issue(
                    "error",
                    "connections.unknown_source",
                    f"{path}.source_id",
                    f"{connection.id} references unknown source {connection.source_id!r}",
                )
            )
        if connection.target_id not in known_elements:
            issues.append(
                _issue(
                    "error",
                    "connections.unknown_target",
                    f"{path}.target_id",
                    f"{connection.id} references unknown target {connection.target_id!r}",
                )
            )
        if connection.source_id in known_elements and connection.target_id in known_elements:
            issues.extend(_validate_connection_ports(connection, path, elements_by_id))

    if not any(issue.severity == "error" for issue in issues):
        issues.extend(_validate_graph_reachability(document))

    return issues


def _validate_element_ports(
    element: DesignElement,
    path: str,
    known_levels: set[str],
    document: StationDesignDocument,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    port_ids = [port.id for port in element.ports]
    for port_id in _duplicates(port_ids):
        issues.append(
            _issue(
                "error",
                "ports.duplicate_id",
                f"{path}.ports",
                f"{element.id} has duplicate port id {port_id!r}",
            )
        )

    for index, port in enumerate(element.ports):
        port_path = f"{path}.ports[{index}]"
        if not port.id:
            issues.append(
                _issue("error", "ports.missing_id", f"{port_path}.id", "port id is required")
            )
        if port.kind not in PORT_KINDS:
            issues.append(
                _issue(
                    "error",
                    "ports.invalid_kind",
                    f"{port_path}.kind",
                    f"{element.id}.{port.id} port kind {port.kind!r} is not supported",
                )
            )
        if port.direction not in PORT_DIRECTIONS:
            issues.append(
                _issue(
                    "error",
                    "ports.invalid_direction",
                    f"{port_path}.direction",
                    f"{element.id}.{port.id} port direction must be in, out, or bidirectional",
                )
            )
        if port.level_id is not None:
            issues.extend(_validate_port_level(element, port.level_id, port_path, known_levels))
        if port.position_m is not None:
            issues.extend(_validate_points((port.position_m,), f"{port_path}.position_m", document))
    return issues


def _validate_port_level(
    element: DesignElement,
    port_level_id: str,
    port_path: str,
    known_levels: set[str],
) -> list[ValidationIssue]:
    if port_level_id not in known_levels:
        return [
            _issue(
                "error",
                "ports.unknown_level",
                f"{port_path}.level_id",
                f"{element.id} port references unknown level {port_level_id!r}",
            )
        ]

    if element.role == "vertical_connector":
        if port_level_id in element.connects_levels:
            return []
        return [
            _issue(
                "error",
                "ports.level_not_connected",
                f"{port_path}.level_id",
                f"{element.id} port level {port_level_id!r} is not in connects_levels",
            )
        ]

    if port_level_id == element.level_id:
        return []
    return [
        _issue(
            "error",
            "ports.level_mismatch",
            f"{port_path}.level_id",
            f"{element.id} port level {port_level_id!r} must match element level {element.level_id!r}",
        )
    ]


def _validate_connection_ports(
    connection,
    path: str,
    elements_by_id: dict[str, DesignElement],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    source = elements_by_id[connection.source_id]
    target = elements_by_id[connection.target_id]
    source_port = _port_by_id(source).get(connection.source_port_id)
    target_port = _port_by_id(target).get(connection.target_port_id)

    if connection.source_port_id is not None and source_port is None:
        issues.append(
            _issue(
                "error",
                "connections.unknown_source_port",
                f"{path}.source_port_id",
                f"{connection.id} references unknown source port "
                f"{connection.source_id}.{connection.source_port_id}",
            )
        )
    if connection.target_port_id is not None and target_port is None:
        issues.append(
            _issue(
                "error",
                "connections.unknown_target_port",
                f"{path}.target_port_id",
                f"{connection.id} references unknown target port "
                f"{connection.target_id}.{connection.target_port_id}",
            )
        )

    if source_port is not None and source_port.direction == "in":
        issues.append(
            _issue(
                "error",
                "connections.source_port_not_output",
                f"{path}.source_port_id",
                f"{connection.id} cannot start from input-only port {source.id}.{source_port.id}",
            )
        )
    if target_port is not None and target_port.direction == "out":
        issues.append(
            _issue(
                "error",
                "connections.target_port_not_input",
                f"{path}.target_port_id",
                f"{connection.id} cannot target output-only port {target.id}.{target_port.id}",
            )
        )
    if connection.bidirectional:
        issues.extend(
            _validate_bidirectional_ports(
                connection,
                path,
                source,
                source_port,
                target,
                target_port,
            )
        )
    return issues


def _validate_bidirectional_ports(
    connection,
    path: str,
    source: DesignElement,
    source_port,
    target: DesignElement,
    target_port,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if source_port is not None and source_port.direction != "bidirectional":
        issues.append(
            _issue(
                "error",
                "connections.source_port_not_bidirectional",
                f"{path}.source_port_id",
                f"{connection.id} is bidirectional but "
                f"{source.id}.{source_port.id} is {source_port.direction}",
            )
        )
    if target_port is not None and target_port.direction != "bidirectional":
        issues.append(
            _issue(
                "error",
                "connections.target_port_not_bidirectional",
                f"{path}.target_port_id",
                f"{connection.id} is bidirectional but "
                f"{target.id}.{target_port.id} is {target_port.direction}",
            )
        )
    return issues


def _port_by_id(element: DesignElement):
    return {port.id: port for port in element.ports}


def _validate_geometry(
    geometry,
    path: str,
    document: StationDesignDocument,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if geometry.shape in {"rect", "point"}:
        if geometry.shape == "rect" and (geometry.width_m <= 0 or geometry.height_m <= 0):
            issues.append(
                _issue(
                    "error",
                    "geometry.invalid_size",
                    path,
                    "rect geometry must have positive width and height",
                )
            )
        issues.extend(
            _validate_points(
                (
                    (geometry.x_m, geometry.y_m),
                    (geometry.x_m + geometry.width_m, geometry.y_m + geometry.height_m),
                ),
                path,
                document,
            )
        )
    elif geometry.shape in {"polygon", "polyline"}:
        min_points = 3 if geometry.shape == "polygon" else 2
        if len(geometry.points_m) < min_points:
            issues.append(
                _issue(
                    "error",
                    "geometry.too_few_points",
                    path,
                    f"{geometry.shape} needs at least {min_points} points",
                )
            )
        issues.extend(_validate_points(geometry.points_m, path, document))
    else:
        issues.append(
            _issue(
                "error",
                "geometry.unknown_shape",
                path,
                f"unknown geometry shape {geometry.shape!r}",
            )
        )
    return issues


def _validate_points(
    points: tuple[tuple[float, float], ...],
    path: str,
    document: StationDesignDocument,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = document.constraints
    for index, (x_m, y_m) in enumerate(points):
        if (
            x_m < 0
            or x_m > constraints.canvas_width_m
            or y_m < 0
            or y_m > constraints.canvas_height_m
        ):
            issues.append(
                _issue(
                    "error",
                    "geometry.out_of_bounds",
                    f"{path}[{index}]",
                    f"point ({x_m}, {y_m}) is outside {constraints.canvas_width_m}m x {constraints.canvas_height_m}m canvas",
                )
            )
    return issues


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity, code, path, message)


def _validate_graph_reachability(document: StationDesignDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        from ..station.graph import StationGraph

        graph = StationGraph.from_design(document, include_walkable_access_edges=False)
    except Exception as exc:
        return [
            _issue(
                "error",
                "graph.compile_failed",
                "connections",
                f"station graph could not be compiled: {type(exc).__name__}: {exc}",
            )
        ]

    entrance_nodes = graph.nodes_matching(kind="entrance")
    platform_nodes = graph.nodes_matching(kind="platform")
    if not entrance_nodes or not platform_nodes:
        return issues

    reachable = _undirected_reachable(graph, {node.node_id for node in entrance_nodes})
    for node in graph.nodes.values():
        if node.kind not in {"entrance", "zone", "facility_entry", "facility_exit", "platform"}:
            continue
        if node.node_id not in reachable:
            issues.append(
                _issue(
                    "error",
                    "graph.unreachable_node",
                    f"elements.{node.element_id or node.node_id}",
                    f"graph node {node.node_id!r} is unreachable from any entrance; add an explicit DesignConnection",
                )
            )

    platform_targets = {node.node_id for node in platform_nodes}
    for entrance in entrance_nodes:
        if graph.shortest_path(entrance.node_id, platform_targets) is None:
            issues.append(
                _issue(
                    "error",
                    "graph.enter_path_missing",
                    f"elements.{entrance.element_id}",
                    f"no directed route from entrance node {entrance.node_id!r} to any platform",
                )
            )

    exit_targets = {
        node.node_id
        for node in graph.nodes_matching(kind="facility_entry", facility_stage="exit_gate")
    }
    if exit_targets:
        for platform in platform_nodes:
            if graph.shortest_path(platform.node_id, exit_targets) is None:
                issues.append(
                    _issue(
                        "error",
                        "graph.exit_path_missing",
                        f"elements.{platform.element_id}",
                        f"no directed exit route from platform node {platform.node_id!r} to any exit gate",
                    )
                )

    return issues


def _undirected_reachable(graph, start_nodes: set[str]) -> set[str]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in graph.nodes}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_node, set()).add(edge.to_node)
        adjacency.setdefault(edge.to_node, set()).add(edge.from_node)

    seen: set[str] = set()
    stack = list(start_nodes)
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        stack.extend(adjacency.get(node_id, ()) - seen)
    return seen
