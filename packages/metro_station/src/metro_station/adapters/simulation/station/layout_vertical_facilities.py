from __future__ import annotations

from dataclasses import replace
from math import hypot

from ..design.schema import DesignElement
from ..facilities.process import FacilityKind, FacilitySpec, QueueLayout
from ..facilities.vertical import (
    VerticalFacilityConfig,
    default_elevator_config,
    default_escalator_config,
    default_stairs_config,
)
from .graph import StationGraph
from .layout_types import Point
from .scenario import StationSandboxScenario


def queue_approach_forward(
    layout: QueueLayout,
    service_entry: Point,
) -> Point | None:
    if not layout.slots:
        return None
    centroid = (
        sum(point[0] for point in layout.slots) / len(layout.slots),
        sum(point[1] for point in layout.slots) / len(layout.slots),
    )
    vector = (service_entry[0] - centroid[0], service_entry[1] - centroid[1])
    if hypot(*vector) <= 0.15:
        return None
    return vector


def vertical_traversal_width(
    element: DesignElement,
    service_entry: Point,
    exit_position: Point,
    scenario: StationSandboxScenario,
) -> float:
    configured = element.metadata.get("traversal_width_m")
    if configured is not None:
        width = float(configured)
    else:
        min_x, min_y, max_x, max_y = element.geometry.bounds()
        forward_x = exit_position[0] - service_entry[0]
        forward_y = exit_position[1] - service_entry[1]
        length = hypot(forward_x, forward_y)
        if length <= 0.001:
            lateral = (1.0, 0.0)
        else:
            lateral = (-forward_y / length, forward_x / length)
        projections = [
            x * lateral[0] + y * lateral[1]
            for x, y in (
                (min_x, min_y),
                (min_x, max_y),
                (max_x, min_y),
                (max_x, max_y),
            )
        ]
        width = max(projections) - min(projections)
    minimum_width = float(scenario.jupedsim_agent_radius_units) * 2.0
    if width <= minimum_width:
        raise ValueError(
            f"vertical connector {element.id!r} traversal_width_m={width:.3f} "
            f"must exceed one body diameter {minimum_width:.3f}"
        )
    return width


def build_vertical_config(
    element: DesignElement,
    scenario: StationSandboxScenario,
) -> VerticalFacilityConfig:
    service_rate = element.capacity or default_vertical_service_rate(element)
    if element.kind == FacilityKind.ELEVATOR.value:
        return VerticalFacilityConfig(
            elevator=default_elevator_config(
                batch_capacity=scenario.elevator_cabin_capacity_persons,
                min_dispatch_persons=scenario.elevator_min_dispatch_persons,
                max_dispatch_wait_seconds=scenario.elevator_max_dispatch_wait_seconds,
                boarding_seconds=scenario.elevator_boarding_seconds,
                travel_seconds=scenario.elevator_cycle_seconds,
                unload_seconds=scenario.elevator_unload_seconds,
            )
        )
    if element.kind == FacilityKind.STAIRS.value:
        return VerticalFacilityConfig(
            stairs=default_stairs_config(
                base_capacity_ppm=service_rate,
                fatigue_cost_up=scenario.stair_fatigue_cost_up,
                fatigue_cost_down=scenario.stair_fatigue_cost_down,
                bidirectional_conflict_factor=scenario.stair_bidirectional_conflict_factor,
            )
        )
    return VerticalFacilityConfig(escalator=default_escalator_config(service_rate))


def link_stair_siblings(facilities: list[FacilitySpec]) -> list[FacilitySpec]:
    stairs_by_element: dict[str, list[FacilitySpec]] = {}
    for facility in facilities:
        if facility.kind != FacilityKind.STAIRS.value:
            continue
        element_key = vertical_element_key(facility)
        if element_key is None:
            continue
        stairs_by_element.setdefault(element_key, []).append(facility)

    sibling_by_id: dict[str, str] = {}
    for stairs in stairs_by_element.values():
        for facility in stairs:
            sibling = next(
                (
                    candidate
                    for candidate in stairs
                    if candidate.facility_id != facility.facility_id
                    and candidate.direction != facility.direction
                ),
                None,
            )
            if sibling is not None:
                sibling_by_id[facility.facility_id] = sibling.facility_id

    if not sibling_by_id:
        return facilities

    linked: list[FacilitySpec] = []
    for facility in facilities:
        sibling_id = sibling_by_id.get(facility.facility_id)
        config = facility.vertical_config
        stairs = config.stairs if config is not None else None
        if sibling_id is None or stairs is None:
            linked.append(facility)
            continue
        linked.append(
            replace(
                facility,
                vertical_config=VerticalFacilityConfig(
                    escalator=config.escalator,
                    elevator=config.elevator,
                    stairs=replace(stairs, sibling_facility_id=sibling_id),
                ),
            )
        )
    return linked


def vertical_element_key(facility: FacilitySpec) -> str | None:
    parts = facility.facility_id.split(":")
    if len(parts) < 2 or parts[0] != "vertical":
        return None
    return parts[1]


def node_position(station_graph: StationGraph, node_id: str) -> Point:
    node = station_graph.nodes.get(node_id)
    if node is None:
        raise ValueError(f"Station graph references missing node {node_id!r}")
    return node.position


def facility_kind_for_element(element: DesignElement) -> str:
    if element.kind == FacilityKind.ELEVATOR.value:
        return FacilityKind.ELEVATOR.value
    if element.kind == FacilityKind.STAIRS.value:
        return FacilityKind.STAIRS.value
    return FacilityKind.ESCALATOR.value


def default_vertical_service_rate(element: DesignElement) -> int:
    if element.kind == FacilityKind.ELEVATOR.value:
        return 24
    if element.kind == FacilityKind.STAIRS.value:
        return 125
    return 75


def vertical_speed(element: DesignElement, scenario: StationSandboxScenario) -> float:
    if element.kind == FacilityKind.ELEVATOR.value:
        return scenario.elevator_speed_units_per_tick
    if element.kind == FacilityKind.STAIRS.value:
        return scenario.stairs_speed_units_per_tick
    return scenario.escalator_speed_units_per_tick


def vertical_speed_m_s(element: DesignElement, scenario: StationSandboxScenario) -> float:
    if element.kind == FacilityKind.ELEVATOR.value:
        return scenario.elevator_speed_m_s
    if element.kind == FacilityKind.STAIRS.value:
        return scenario.stairs_speed_m_s
    return scenario.escalator_speed_m_s
