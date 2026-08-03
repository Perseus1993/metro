"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from shapely.geometry import Polygon

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.station.graph import StationGraph
from .preset_trajectory_topology import (
    facility_graph_backed,
    level_changes_service_backed,
    positions_inside_footprints,
    stage_sequence_valid,
    vertical_services_topological,
)
from metro_station.adapters.simulation.runtime.snapshots import FrameSnapshot


def audit_random_passengers(
    model,
    document: StationDesignDocument,
    *,
    sample_seed: int,
    sample_count: int = 3,
) -> list[dict[str, Any]]:
    passenger_ids = sorted(model.passenger_goal_runtimes)
    graph = model.layout_graph.station_graph or StationGraph.from_design(document)
    facilities = {facility.facility_id: facility for facility in model.layout_graph.facilities}
    snapshots = _passenger_snapshots(model.frames)
    physical_stages = _physical_stage_events(model)
    services = _service_events(model)
    terminals = {event.passenger_id: event for event in model.passenger_terminal_events}
    selected_ids = _sample_ids(passenger_ids, terminals, sample_seed, sample_count)
    parity_mismatches = _parity_mismatch_ids(model.goal_parity.report(model, include_events=False))
    footprints = {level.id: Polygon(level.footprint).buffer(0.75) for level in document.levels}

    return [
        _audit_passenger(
            passenger_id,
            graph=graph,
            facilities=facilities,
            snapshots=snapshots.get(passenger_id, []),
            stages=physical_stages.get(passenger_id, []),
            services=services.get(passenger_id, []),
            terminal=terminals.get(passenger_id),
            runtime=model.passenger_goal_runtimes[passenger_id],
            footprints=footprints,
            parity_mismatches=parity_mismatches,
        )
        for passenger_id in selected_ids
    ]


def _audit_passenger(
    passenger_id: int,
    *,
    graph: StationGraph,
    facilities: dict[str, Any],
    snapshots: list[tuple[float, Any]],
    stages: list[Any],
    services: list[Any],
    terminal: Any,
    runtime: Any,
    footprints: dict[str, Any],
    parity_mismatches: set[int],
) -> dict[str, Any]:
    level_sequence = _dedupe(item.current_level_id for _, item in snapshots)
    level_changes = list(zip(level_sequence, level_sequence[1:]))
    stage_sequence = [event.stage for event in stages]
    intent = None if terminal is None else str(terminal.intent)
    checks = {
        "has_physical_samples": bool(snapshots),
        "sample_times_non_decreasing": _non_decreasing(
            [time_s for time_s, _ in snapshots]
        ),
        "coordinates_finite": all(
            math.isfinite(item.x) and math.isfinite(item.y) for _, item in snapshots
        ),
        "positions_inside_level": positions_inside_footprints(snapshots, footprints),
        "known_levels_only": all(level_id in footprints for level_id in level_sequence),
        "level_changes_service_backed": level_changes_service_backed(level_changes, services),
        "level_sequence_matches_journey": len(level_changes)
        == graph.vertical_transfer_count_for_intent(intent or ""),
        "vertical_services_topological": vertical_services_topological(
            services,
            facilities,
            graph,
        ),
        "service_facilities_exist": all(event.facility_id in facilities for event in stages),
        "service_facilities_graph_backed": all(
            facility_graph_backed(graph, facilities.get(event.facility_id), event.stage)
            for event in stages
        ),
        "stage_sequence_matches_journey": stage_sequence_valid(intent, stage_sequence, graph),
        "goal_graph_complete": runtime.graph.node(runtime.state.current_node_id).kind == "complete",
        "terminal_reached": terminal is not None,
        "physical_goal_parity": passenger_id not in parity_mismatches,
    }
    return {
        "passenger_id": passenger_id,
        "persons": None if terminal is None else int(terminal.persons),
        "intent": intent,
        "sample_count": len(snapshots),
        "distance_m": round(_trajectory_distance(snapshots), 3),
        "first_time_s": None if not snapshots else snapshots[0][0],
        "last_time_s": None if not snapshots else snapshots[-1][0],
        "level_sequence": level_sequence,
        "service_stage_sequence": stage_sequence,
        "service_facility_ids": [event.facility_id for event in stages],
        "goal_event_sequence": [transition.event_kind for transition in runtime.transitions],
        "trajectory_points": _representative_points(snapshots),
        "checks": checks,
        "status": "ok" if all(checks.values()) else "review",
    }


def _passenger_snapshots(frames) -> dict[int, list[tuple[float, Any]]]:
    grouped: dict[int, list[tuple[float, Any]]] = defaultdict(list)
    for raw_frame in frames:
        frame = FrameSnapshot.from_any(raw_frame)
        for passenger in frame.passengers:
            grouped[int(passenger.id)].append((float(frame.time_seconds), passenger))
    return grouped


def _physical_stage_events(model) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for event in model.goal_parity.events:
        if event.stream == "physical" and event.kind == "service_completed" and event.stage:
            grouped[int(event.passenger_id)].append(event)
    return grouped


def _service_events(model) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = defaultdict(list)
    for event in model.facility_service_events:
        for passenger_id in event.passenger_ids:
            grouped[int(passenger_id)].append(event)
    for events in grouped.values():
        events.sort(key=lambda event: (event.start_time, event.event_id))
    return grouped


def _parity_mismatch_ids(report: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for key, values in report.items():
        if not key.endswith("mismatches") and key != "post_terminal_lifecycle_events":
            continue
        if isinstance(values, list):
            ids.update(int(item["passenger_id"]) for item in values if "passenger_id" in item)
    return ids


def _sample_ids(
    passenger_ids: list[int],
    terminals: dict[int, Any],
    seed: int,
    count: int,
) -> list[int]:
    if len(passenger_ids) <= count:
        return passenger_ids
    rng = random.Random(seed)
    ids_by_intent: dict[str, list[int]] = defaultdict(list)
    for passenger_id in passenger_ids:
        terminal = terminals.get(passenger_id)
        intent = "unknown" if terminal is None else str(terminal.intent)
        ids_by_intent[intent].append(passenger_id)
    selected = [rng.choice(ids) for _, ids in sorted(ids_by_intent.items())]
    if len(selected) > count:
        selected = rng.sample(selected, count)
    remaining = [passenger_id for passenger_id in passenger_ids if passenger_id not in selected]
    selected.extend(rng.sample(remaining, min(count - len(selected), len(remaining))))
    return sorted(selected)


def _dedupe(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is not None and (not result or result[-1] != value):
            result.append(str(value))
    return result


def _non_decreasing(values: list[float]) -> bool:
    return all(left <= right for left, right in zip(values, values[1:]))


def _trajectory_distance(snapshots) -> float:
    positions = [(float(item.x), float(item.y)) for _, item in snapshots]
    return sum(
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(positions, positions[1:])
    )


def _representative_points(snapshots, limit: int = 5) -> list[dict[str, Any]]:
    if not snapshots:
        return []
    last_index = len(snapshots) - 1
    indexes = sorted({round(last_index * offset / max(1, limit - 1)) for offset in range(limit)})
    return [
        {
            "time_s": time_s,
            "x": item.x,
            "y": item.y,
            "level_id": item.current_level_id,
            "state": item.state,
            "goal_node_id": (item.goal_graph or {}).get("state", {}).get("current_node_id"),
        }
        for index in indexes
        for time_s, item in [snapshots[index]]
    ]
