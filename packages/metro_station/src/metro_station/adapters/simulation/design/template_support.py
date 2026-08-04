from __future__ import annotations

from dataclasses import replace

from .helpers import gate_direction as _gate_direction
from .schema import (
    DesignConnection,
    DesignElement,
    DesignPort,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)
from .vertical_landing import design_level_walkable_geometry, vertical_landing_position


def rect(x: float, y: float, width: float, height: float) -> ElementGeometry:
    return ElementGeometry("rect", x_m=x, y_m=y, width_m=width, height_m=height)


def polygon(points: tuple[tuple[float, float], ...]) -> ElementGeometry:
    return ElementGeometry("polygon", points_m=points)


def polyline(points: tuple[tuple[float, float], ...]) -> ElementGeometry:
    return ElementGeometry("polyline", points_m=points)


def lane(
    id: str,
    owner: str,
    level: str,
    x: float,
    y: float,
    width: float,
    height: float,
    service_point: tuple[float, float],
    capacity: int,
    direction_deg: float,
    label: str,
) -> QueueSpec:
    return QueueSpec(
        id=id,
        owner_element_id=owner,
        kind="lane",
        level_id=level,
        geometry=rect(x, y, width, height),
        service_point_m=service_point,
        capacity=capacity,
        direction_deg=direction_deg,
        label=label,
    )


def _with_standard_graph_ports(document: StationDesignDocument) -> StationDesignDocument:
    elements = tuple(
        _with_standard_ports(element, document) for element in document.elements
    )
    elements_by_id = {element.id: element for element in elements}
    connections = tuple(
        _with_standard_connection_ports(connection, elements_by_id)
        for connection in document.connections
    )
    connections = _with_standard_access_connections(elements, connections)
    connections = _with_standard_zone_connections(elements, connections)
    return replace(document, elements=elements, connections=connections)


def with_standard_graph_contract(document: StationDesignDocument) -> StationDesignDocument:
    """Public generation boundary for standard ports and floor access connections."""

    return _with_standard_graph_ports(document)


def _with_standard_ports(
    element: DesignElement,
    document: StationDesignDocument,
) -> DesignElement:
    reserved_ids = (
        {"service", "release", "paid", "unpaid"}
        if element.kind == "gate"
        else {
            _level_port_id(level_id) for level_id in element.connects_levels
        }
        if element.role == "vertical_connector"
        else set()
    )
    ports = [port for port in element.ports if port.id not in reserved_ids]
    known_ids = {port.id for port in ports}
    for port in _standard_ports_for_element(element, document):
        if port.id not in known_ids:
            ports.append(port)
            known_ids.add(port.id)
    return replace(element, ports=tuple(ports))


def _standard_ports_for_element(
    element: DesignElement,
    document: StationDesignDocument,
) -> tuple[DesignPort, ...]:
    if element.role == "vertical_connector":
        return tuple(
            DesignPort(
                _level_port_id(level_id),
                "vertical",
                level_id=level_id,
                position_m=_vertical_port_position(element, level_id, document),
            )
            for level_id in element.connects_levels
        )

    if element.kind == "gate":
        center = element.geometry.center()
        direction = _gate_direction(element)
        ports = [
            DesignPort(
                "service",
                "service",
                direction="in",
                level_id=element.level_id,
                position_m=center,
            ),
            DesignPort(
                "release",
                "release",
                direction="out",
                level_id=element.level_id,
                position_m=center,
            ),
        ]
        if direction in {"entry", "bidirectional"}:
            ports.append(
                DesignPort(
                    "paid",
                    "fare_paid",
                    level_id=element.level_id,
                    position_m=center,
                    metadata={"graph_node_id": f"gate:{element.id}:paid"},
                )
            )
        if direction in {"exit", "bidirectional"}:
            ports.append(
                DesignPort(
                    "unpaid",
                    "fare_unpaid",
                    direction="out",
                    level_id=element.level_id,
                    position_m=center,
                    metadata={"graph_node_id": f"gate:{element.id}:unpaid"},
                )
            )
        return tuple(ports)

    if element.kind == "walkable_area" or element.role == "floor":
        # Zone anchors are selected from the obstacle-subtracted walkable
        # domain by graph compilation.  Persisting the bounding-box centre as
        # an authored port lets an obstacle invalidate the point while the
        # compiler silently uses another one, creating two endpoint truths.
        return (
            DesignPort(
                "walk",
                "walk",
                level_id=element.level_id,
                position_m=None,
            ),
        )

    if element.kind in {"entrance", "platform_edge"}:
        return (
            DesignPort(
                "walk",
                "walk",
                level_id=element.level_id,
                position_m=element.geometry.center(),
            ),
        )

    return ()


def _with_standard_connection_ports(
    connection: DesignConnection,
    elements_by_id: dict[str, DesignElement],
) -> DesignConnection:
    source = elements_by_id.get(connection.source_id)
    target = elements_by_id.get(connection.target_id)
    if source is None or target is None:
        return connection

    return replace(
        connection,
        source_port_id=connection.source_port_id
        or _standard_connection_port_id(source, target, "source"),
        target_port_id=connection.target_port_id
        or _standard_connection_port_id(target, source, "target"),
        bidirectional=connection.bidirectional
        and _standard_connection_is_bidirectional(
            source,
            connection.source_port_id or _standard_connection_port_id(source, target, "source"),
            target,
            connection.target_port_id or _standard_connection_port_id(target, source, "target"),
        ),
    )


def _standard_connection_port_id(
    element: DesignElement,
    other: DesignElement,
    endpoint: str,
) -> str | None:
    if element.role == "vertical_connector":
        if other.level_id in element.connects_levels:
            return _level_port_id(other.level_id)
        return None

    if element.kind == "gate":
        direction = _gate_direction(element)
        if endpoint == "target":
            return "service"
        if direction == "exit":
            return "unpaid"
        return "release"

    if element.kind in {"entrance", "walkable_area", "platform_edge"} or element.role == "floor":
        return "walk"

    return None


def _standard_connection_is_bidirectional(
    source: DesignElement,
    source_port_id: str | None,
    target: DesignElement,
    target_port_id: str | None,
) -> bool:
    source_port = _port_by_id(source).get(source_port_id)
    target_port = _port_by_id(target).get(target_port_id)
    return _port_allows_bidirectional(source_port) and _port_allows_bidirectional(target_port)


def _port_allows_bidirectional(port: DesignPort | None) -> bool:
    return port is not None and port.direction == "bidirectional"


def _port_by_id(element: DesignElement) -> dict[str | None, DesignPort]:
    return {port.id: port for port in element.ports}


def _with_standard_access_connections(
    elements: tuple[DesignElement, ...],
    connections: tuple[DesignConnection, ...],
) -> tuple[DesignConnection, ...]:
    zone_elements_by_level = _zone_elements_by_level(elements)
    existing_ids = {connection.id for connection in connections}
    result = list(connections)

    for element in elements:
        for port_id, level_id in _required_floor_access_ports(element):
            zones = zone_elements_by_level.get(level_id, ())
            if not zones or _has_zone_connection(connections, element.id, port_id, zones):
                continue
            zone = _nearest_zone(element, port_id, zones)
            connection_id = _access_connection_id(element.id, port_id, zone.id)
            if connection_id in existing_ids:
                continue
            result.append(
                DesignConnection(
                    connection_id,
                    element.id,
                    zone.id,
                    "walk",
                    bidirectional=_floor_access_is_bidirectional(element),
                    source_port_id=port_id,
                    target_port_id="walk",
                )
            )
            existing_ids.add(connection_id)

    return tuple(result)


def _with_standard_zone_connections(
    elements: tuple[DesignElement, ...],
    connections: tuple[DesignConnection, ...],
) -> tuple[DesignConnection, ...]:
    zone_elements_by_level = _zone_elements_by_level(elements)
    existing_ids = {connection.id for connection in connections}
    result = list(connections)

    for zones in zone_elements_by_level.values():
        for zone in zones:
            if len(zones) < 2 or _has_zone_to_zone_connection(result, zone.id, zones):
                continue
            target = _nearest_other_zone(zone, zones)
            connection_id = _zone_connection_id(zone.id, target.id)
            if connection_id in existing_ids:
                continue
            result.append(
                DesignConnection(
                    connection_id,
                    zone.id,
                    target.id,
                    "walk",
                    source_port_id="walk",
                    target_port_id="walk",
                )
            )
            existing_ids.add(connection_id)

    return tuple(result)


def _zone_elements_by_level(
    elements: tuple[DesignElement, ...],
) -> dict[str, tuple[DesignElement, ...]]:
    zones: dict[str, list[DesignElement]] = {}
    for element in elements:
        if not _is_graph_zone(element):
            continue
        zones.setdefault(element.level_id, []).append(element)
    return {level_id: tuple(items) for level_id, items in zones.items()}


def _is_graph_zone(element: DesignElement) -> bool:
    return (element.role == "floor" or element.kind == "walkable_area") and element.metadata.get(
        "graph_node", True
    )


def _required_floor_access_ports(element: DesignElement) -> tuple[tuple[str, str], ...]:
    if element.kind == "entrance":
        return (("walk", element.level_id),)
    if element.kind == "platform_edge":
        return (("walk", element.level_id),)
    if element.role == "vertical_connector":
        return tuple((_level_port_id(level_id), level_id) for level_id in element.connects_levels)
    if element.kind == "gate":
        direction = _gate_direction(element)
        ports: list[tuple[str, str]] = []
        if direction in {"entry", "bidirectional"}:
            ports.append(("release", element.level_id))
        if direction in {"exit", "bidirectional"}:
            ports.append(("unpaid", element.level_id))
        return tuple(ports)
    return ()


def _floor_access_is_bidirectional(element: DesignElement) -> bool:
    return element.role == "vertical_connector"


def _has_zone_connection(
    connections: tuple[DesignConnection, ...],
    element_id: str,
    port_id: str,
    zones: tuple[DesignElement, ...],
) -> bool:
    zone_ids = {zone.id for zone in zones}
    for connection in connections:
        if (
            connection.source_id == element_id
            and connection.source_port_id == port_id
            and connection.target_id in zone_ids
        ):
            return True
        if (
            connection.target_id == element_id
            and connection.target_port_id == port_id
            and connection.source_id in zone_ids
        ):
            return True
    return False


def _has_zone_to_zone_connection(
    connections: tuple[DesignConnection, ...],
    zone_id: str,
    zones: tuple[DesignElement, ...],
) -> bool:
    zone_ids = {zone.id for zone in zones}
    for connection in connections:
        if connection.source_id == zone_id and connection.target_id in zone_ids:
            return True
        if connection.target_id == zone_id and connection.source_id in zone_ids:
            return True
    return False


def _nearest_other_zone(
    zone: DesignElement,
    zones: tuple[DesignElement, ...],
) -> DesignElement:
    return min(
        (candidate for candidate in zones if candidate.id != zone.id),
        key=lambda candidate: _distance(zone.geometry.center(), candidate.geometry.center()),
    )


def _nearest_zone(
    element: DesignElement,
    port_id: str,
    zones: tuple[DesignElement, ...],
) -> DesignElement:
    port_position = _port_position(element, port_id)
    return min(zones, key=lambda zone: _distance(port_position, zone.geometry.center()))


def _port_position(element: DesignElement, port_id: str) -> tuple[float, float]:
    for port in element.ports:
        if port.id == port_id and port.position_m is not None:
            return port.position_m
    return element.geometry.center()


def _access_connection_id(element_id: str, port_id: str, zone_id: str) -> str:
    safe_port_id = port_id.replace(":", "_")
    return f"conn_access_{element_id}_{safe_port_id}_to_{zone_id}"


def _zone_connection_id(source_id: str, target_id: str) -> str:
    return f"conn_zone_{source_id}_to_{target_id}"


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5


def _level_port_id(level_id: str) -> str:
    return f"level:{level_id}"


def _vertical_port_position(
    element: DesignElement,
    level_id: str,
    document: StationDesignDocument,
) -> tuple[float, float]:
    return vertical_landing_position(
        element,
        level_id,
        document.level_by_id(),
        walkable_geometry=design_level_walkable_geometry(document, level_id),
    )


def _footprint(
    x: float,
    y: float,
    width: float,
    height: float,
) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + width, y), (x + width, y + height), (x, y + height))


def _replace_level(element: DesignElement, old: str, new: str) -> DesignElement:
    level_id = new if element.level_id == old else element.level_id
    connects_levels = tuple(new if level == old else level for level in element.connects_levels)
    return replace(
        element,
        id=element.id.replace(old.removesuffix("_platform"), new.removesuffix("_platform")),
        level_id=level_id,
        connects_levels=connects_levels,
        ports=(),
    )


def _three_level_element(element: DesignElement) -> DesignElement:
    if element.role == "vertical_connector" and element.level_id == "b1_concourse":
        connects_levels = ("b1_concourse", "b2_transfer")
        if element.kind == "elevator":
            connects_levels = ("b1_concourse", "b2_transfer", "b3_platform")
        return replace(
            element,
            connects_levels=connects_levels,
            ports=(),
        )
    return _replace_level(element, "b2_platform", "b3_platform")


def _replace_queue_level(queue: QueueSpec, old: str, new: str) -> QueueSpec:
    level_id = new if queue.level_id == old else queue.level_id
    return QueueSpec(
        id=queue.id,
        owner_element_id=queue.owner_element_id,
        kind=queue.kind,
        level_id=level_id,
        geometry=queue.geometry,
        service_point_m=queue.service_point_m,
        capacity=queue.capacity,
        spacing_m=queue.spacing_m,
        direction_deg=queue.direction_deg,
        label=queue.label,
        service_direction=queue.service_direction,
    )
