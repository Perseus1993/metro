from __future__ import annotations

from dataclasses import dataclass, replace

from metro_station.adapters.simulation.design.schema import StationDesignDocument

from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout


@dataclass(frozen=True)
class InvalidLayoutCase:
    case_id: str
    expected_code: str
    document: StationDesignDocument


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
