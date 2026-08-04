from __future__ import annotations

from dataclasses import dataclass, replace

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    DesignPort,
    ElementGeometry,
    StationDesignDocument,
)

from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout


@dataclass(frozen=True)
class InvalidLayoutCase:
    case_id: str
    expected_code: str
    document: StationDesignDocument
    allowed_codes: tuple[str, ...] = ()

    @property
    def expected_codes(self) -> tuple[str, ...]:
        return self.allowed_codes or (self.expected_code,)


def invalid_layout_cases() -> tuple[InvalidLayoutCase, ...]:
    valid = generate_layout(_baseline_recipe())
    return (
        InvalidLayoutCase(
            "duplicate_element_id",
            "elements.duplicate_id",
            replace(valid, elements=(*valid.elements, valid.elements[0])),
        ),
        InvalidLayoutCase(
            "unknown_queue_owner",
            "queues.unknown_owner",
            replace(
                valid,
                queues=(
                    replace(valid.queues[0], owner_element_id="missing_facility"),
                    *valid.queues[1:],
                ),
            ),
        ),
        InvalidLayoutCase(
            "queue_outside_footprint",
            "layout.queue_outside_level_footprint",
            replace(
                valid,
                queues=(
                    replace(
                        valid.queues[0],
                        geometry=valid.queues[0].geometry.moved_to(110.0, 70.0),
                    ),
                    *valid.queues[1:],
                ),
            ),
        ),
        InvalidLayoutCase(
            "connector_unknown_level",
            "connectors.unknown_level",
            _connector_unknown_level(valid),
        ),
        InvalidLayoutCase(
            "platform_disconnected",
            "graph.unreachable_node",
            _platform_disconnected(valid),
            (
                "graph.unreachable_node",
                "graph.enter_path_missing",
                "graph.exit_path_missing",
            ),
        ),
        InvalidLayoutCase(
            "narrow_neck_blocks_body_domain",
            "geometry.level_domain_disconnected",
            _with_wall(valid, "narrow_neck", 60.0, 4.0, 1.0, 41.8),
        ),
        InvalidLayoutCase(
            "multipolygon_level_domain",
            "geometry.level_domain_disconnected",
            _with_wall(valid, "full_partition", 60.0, 4.0, 1.0, 42.0),
        ),
        InvalidLayoutCase(
            "obstacle_on_authored_walk_endpoint",
            "geometry.walk_edge_not_traversable",
            _walk_endpoint_outside_domain(valid),
        ),
        InvalidLayoutCase(
            "entrance_sealed_from_continuous_domain",
            "geometry.entrance_platform_unreachable",
            _entrance_endpoint_outside_domain(valid),
            (
                "geometry.walk_edge_not_traversable",
                "geometry.entrance_platform_unreachable",
            ),
        ),
    )


def _baseline_recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="invalid-case-baseline",
        seed=1,
        archetype="two_level_island",
        entrance_count=1,
        gate_count=1,
        elevator_count=1,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=False,
        asset_density="standard",
        geometry_variant=4,
    )


def _connector_unknown_level(document: StationDesignDocument) -> StationDesignDocument:
    elements = tuple(
        replace(element, connects_levels=(*element.connects_levels, "missing_level"))
        if element.id == "elevator_a"
        else element
        for element in document.elements
    )
    return replace(document, elements=elements)


def _platform_disconnected(document: StationDesignDocument) -> StationDesignDocument:
    platform_ids = {element.id for element in document.elements if element.kind == "platform_edge"}
    return replace(
        document,
        connections=tuple(
            connection
            for connection in document.connections
            if connection.source_id not in platform_ids and connection.target_id not in platform_ids
        ),
    )


def _with_wall(
    document: StationDesignDocument,
    wall_id: str,
    x_m: float,
    y_m: float,
    width_m: float,
    height_m: float,
) -> StationDesignDocument:
    wall = DesignElement(
        wall_id,
        "obstacle",
        "b1_concourse",
        ElementGeometry(
            "rect",
            x_m=x_m,
            y_m=y_m,
            width_m=width_m,
            height_m=height_m,
        ),
        wall_id,
        "obstacle",
        False,
        True,
        metadata={"blocking": True},
    )
    return replace(document, elements=(*document.elements, wall))


def _walk_endpoint_outside_domain(document: StationDesignDocument) -> StationDesignDocument:
    corridor = document.element_by_id()["b2_back_corridor"]
    bad_port = DesignPort(
        "bad_walk",
        "walk",
        level_id="b2_platform",
        position_m=(9.0, 5.0),
    )
    elements = tuple(
        replace(element, ports=(*corridor.ports, bad_port))
        if element.id == corridor.id
        else element
        for element in document.elements
    )
    connections = tuple(
        replace(connection, target_port_id="bad_walk")
        if connection.id == "conn_platform_to_back_corridor"
        else connection
        for connection in document.connections
    )
    return replace(document, elements=elements, connections=connections)


def _entrance_endpoint_outside_domain(
    document: StationDesignDocument,
) -> StationDesignDocument:
    entrance = document.element_by_id()["entrance_a"]
    ports = tuple(
        replace(port, position_m=(3.0, 3.0)) if port.id == "walk" else port
        for port in entrance.ports
    )
    return replace(
        document,
        elements=tuple(
            replace(element, ports=ports) if element.id == entrance.id else element
            for element in document.elements
        ),
    )
