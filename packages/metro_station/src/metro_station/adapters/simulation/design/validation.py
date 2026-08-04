from __future__ import annotations

from math import isfinite

from .geometry_validation import (
    validate_geometry as _validate_geometry,
    validate_points as _validate_points,
)
from .layout_rules import validate_flexible_layout
from .schema import (
    MAX_COMPILED_QUEUE_CAPACITY,
    MIN_COMPILED_QUEUE_SPACING_M,
    SCHEMA_VERSION,
    DesignElement,
    StationDesignDocument,
)
from .validation_issue import ValidationIssue, issue as _issue


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
CONNECTION_KINDS = {"walk", "vertical", "service"}
MAX_DESIGN_ID_LENGTH = 255


def validate_design_schema(document: StationDesignDocument) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    constraints = document.constraints

    if document.schema_version != SCHEMA_VERSION:
        issues.append(
            _issue(
                "error",
                "schema.unsupported",
                "schema_version",
                f"design schema must be {SCHEMA_VERSION!r}; got {document.schema_version!r}",
            )
        )
    issues.extend(_validate_id(document.id, "id", "design"))

    if document.units != "meters":
        issues.append(_issue("error", "units.unsupported", "units", "design units must be meters"))

    if not document.levels:
        issues.append(_issue("error", "levels.empty", "levels", "design must contain a level"))
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

    duplicate_orders = _duplicates([str(level.order) for level in document.levels])
    for order in duplicate_orders:
        issues.append(
            _issue(
                "error",
                "levels.duplicate_order",
                "levels",
                f"duplicate level order {order}",
            )
        )
    duplicate_elevations = _duplicates([str(level.elevation_m) for level in document.levels])
    for elevation in duplicate_elevations:
        issues.append(
            _issue(
                "error",
                "levels.duplicate_elevation",
                "levels",
                f"duplicate level elevation {elevation}",
            )
        )

    for index, level in enumerate(document.levels):
        path = f"levels[{index}]"
        issues.extend(_validate_id(level.id, f"{path}.id", "level"))
        if not isfinite(float(level.elevation_m)) or not isfinite(
            float(level.floor_to_floor_height_m)
        ):
            issues.append(
                _issue(
                    "error",
                    "numbers.non_finite",
                    path,
                    f"{level.id} elevation and floor height must be finite",
                )
            )
            continue
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
        issues.extend(_validate_id(element.id, f"{path}.id", "element"))
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
        if element.capacity is not None and (
            not isfinite(float(element.capacity)) or element.capacity <= 0
        ):
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
        issues.extend(_validate_id(queue.id, f"{path}.id", "queue"))
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
        if queue.service_direction not in {None, "up", "down", "in", "out"}:
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_service_direction",
                    f"{path}.service_direction",
                    f"{queue.id} service_direction must be in, out, up, down, or null",
                )
            )
        if type(queue.capacity) is not int:
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_capacity",
                    f"{path}.capacity",
                    f"{queue.id} capacity must be an integer",
                )
            )
        elif not isfinite(float(queue.capacity)) or queue.capacity <= 0:
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_capacity",
                    f"{path}.capacity",
                    f"{queue.id} capacity must be positive",
                )
            )
        elif queue.capacity > MAX_COMPILED_QUEUE_CAPACITY:
            issues.append(
                _issue(
                    "error",
                    "queues.capacity_exceeds_compiler_limit",
                    f"{path}.capacity",
                    f"{queue.id} capacity must not exceed "
                    f"{MAX_COMPILED_QUEUE_CAPACITY}",
                )
            )
        if (
            not isfinite(float(queue.spacing_m))
            or queue.spacing_m < MIN_COMPILED_QUEUE_SPACING_M
        ):
            issues.append(
                _issue(
                    "error",
                    "queues.invalid_spacing",
                    f"{path}.spacing_m",
                    f"{queue.id} spacing must be at least "
                    f"{MIN_COMPILED_QUEUE_SPACING_M} m",
                )
            )
        issues.extend(_validate_geometry(queue.geometry, f"{path}.geometry", document))
        issues.extend(
            _validate_points((queue.service_point_m,), f"{path}.service_point_m", document)
        )

    connection_ids = [connection.id for connection in document.connections]
    for connection_id in _duplicates(connection_ids):
        issues.append(
            _issue(
                "error",
                "connections.duplicate_id",
                "connections",
                f"duplicate connection id {connection_id!r}",
            )
        )

    for index, connection in enumerate(document.connections):
        path = f"connections[{index}]"
        issues.extend(_validate_id(connection.id, f"{path}.id", "connection"))
        if connection.kind not in CONNECTION_KINDS:
            issues.append(
                _issue(
                    "error",
                    "connections.invalid_kind",
                    f"{path}.kind",
                    f"{connection.id} kind must be one of {sorted(CONNECTION_KINDS)!r}",
                )
            )
        if not isinstance(connection.bidirectional, bool):
            issues.append(
                _issue(
                    "error",
                    "connections.invalid_bidirectional",
                    f"{path}.bidirectional",
                    f"{connection.id} bidirectional must be true or false",
                )
            )
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

    unsafe_geometry_codes = {
        "numbers.non_finite",
        "geometry.non_finite",
        "geometry.out_of_bounds",
        "geometry.invalid_size",
    }
    if not any(issue.code in unsafe_geometry_codes for issue in issues):
        issues.extend(
            ValidationIssue(violation.severity, violation.code, violation.path, violation.message)
            for violation in validate_flexible_layout(document)
        )

    return issues


def validate_design(document: StationDesignDocument) -> list[ValidationIssue]:
    """Compatibility facade for full schema + topology validation."""

    from ..compilation.validation import validate_station_design

    return validate_station_design(document)


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
        id_issues = _validate_id(port.id, f"{port_path}.id", "port")
        issues.extend(id_issues)
        if any(issue.code == "ids.blank" for issue in id_issues):
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


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _validate_id(value: object, path: str, label: str) -> list[ValidationIssue]:
    text = str(value)
    if not text.strip():
        return [_issue("error", "ids.blank", path, f"{label} id must not be blank")]
    if len(text) > MAX_DESIGN_ID_LENGTH:
        return [
            _issue(
                "error",
                "ids.too_long",
                path,
                f"{label} id exceeds {MAX_DESIGN_ID_LENGTH} characters",
            )
        ]
    return []
