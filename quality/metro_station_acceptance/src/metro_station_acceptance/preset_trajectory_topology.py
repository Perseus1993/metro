"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from typing import Any

from shapely.geometry import Point

from metro_station.adapters.simulation.planning.plan import FacilityStage
from metro_station.adapters.simulation.station.graph import StationGraph


def facility_graph_backed(graph: StationGraph, facility: Any, stage: str | None) -> bool:
    if facility is None or stage is None:
        return False
    element_id = _facility_element_id(str(facility.facility_id))
    node_ids = set(graph.node_ids_for_element(element_id))
    if not node_ids:
        return False
    if stage == FacilityStage.BOARDING_DOOR.value:
        return any(graph.nodes[node_id].kind == "platform" for node_id in node_ids)
    return any(
        edge.facility_stage == stage
        and edge.from_node in node_ids
        and edge.to_node in node_ids
        for edge in graph.edges
    )


def positions_inside_footprints(snapshots, footprints: dict[str, Any]) -> bool:
    return all(
        item.current_level_id in footprints
        and footprints[item.current_level_id].covers(Point(float(item.x), float(item.y)))
        for _, item in snapshots
    )


def level_changes_service_backed(level_changes, services) -> bool:
    transitions = {
        (event.from_level, event.to_level)
        for event in services
        if event.from_level and event.to_level and event.from_level != event.to_level
    }
    return all(change in transitions for change in level_changes)


def vertical_services_topological(services, facilities, graph: StationGraph) -> bool:
    for event in services:
        if not event.from_level or event.from_level == event.to_level:
            continue
        facility = facilities.get(event.facility_id)
        if facility is None:
            return False
        if (facility.entry_level_id, facility.exit_level_id) != (
            event.from_level,
            event.to_level,
        ):
            return False
        if not facility_graph_backed(
            graph,
            facility,
            FacilityStage.VERTICAL_TRANSFER.value,
        ):
            return False
    return True


def stage_sequence_valid(intent: str | None, stages: list[str], graph: StationGraph) -> bool:
    vertical_count = graph.vertical_transfer_count_for_intent(intent or "")
    expected = {
        "enter_and_board": [
            FacilityStage.ENTRY_GATE.value,
            *([FacilityStage.VERTICAL_TRANSFER.value] * vertical_count),
            FacilityStage.BOARDING_DOOR.value,
        ],
        "exit_station": [
            *([FacilityStage.VERTICAL_TRANSFER.value] * vertical_count),
            FacilityStage.EXIT_GATE.value,
        ],
        "transfer": [
            *([FacilityStage.VERTICAL_TRANSFER.value] * vertical_count),
            FacilityStage.BOARDING_DOOR.value,
        ],
    }.get(intent)
    return expected is not None and stages == expected


def _facility_element_id(facility_id: str) -> str:
    prefix, remainder = facility_id.split(":", 1)
    if prefix == "vertical":
        return remainder.split(":", 1)[0]
    return remainder.split(":lane_", 1)[0]
