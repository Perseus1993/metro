from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_WALKING_STATES = {
    "entering_station",
    "walking_to_vertical",
    "walking_to_platform",
    "walking_to_exit_gate",
    "walking_to_transfer",
}


def export_anonymized_xy_observations(
    replay_path: str | Path,
    output_path: str | Path,
) -> int:
    """Export only anonymous ``id,t,x,y`` observations from simulation truth."""

    source = json.loads(Path(replay_path).read_text(encoding="utf-8"))
    trace = source.get("simulation_trace")
    if not isinstance(trace, Mapping) or trace.get("schema_version") != "simulation_trace.v1":
        raise ValueError("input must contain simulation_trace.v1 authoritative snapshots")

    anonymous_ids: dict[str, str] = {}
    authoritative: dict[tuple[str, float], tuple[float, float]] = {}
    snapshot_states: dict[tuple[str, float], str] = {}
    for snapshot in trace.get("snapshots", ()):
        if not isinstance(snapshot, Mapping):
            raise ValueError("simulation snapshot must be an object")
        time_seconds = _finite_float(snapshot.get("time_seconds"), "time_seconds")
        passengers = snapshot.get("passengers", ())
        if not isinstance(passengers, list):
            raise ValueError("simulation snapshot passengers must be an array")
        for passenger in passengers:
            if not isinstance(passenger, Mapping):
                raise ValueError("simulation passenger must be an object")
            source_id = str(passenger.get("id"))
            anonymous_ids.setdefault(
                source_id,
                f"p{len(anonymous_ids) + 1:04d}",
            )
            key = (source_id, round(time_seconds, 6))
            authoritative[key] = (
                _finite_float(passenger.get("x"), "x"),
                _finite_float(passenger.get("y"), "y"),
            )
            snapshot_states[key] = str(passenger.get("state", ""))

    movement_trace = trace.get("movement_trace")
    if isinstance(movement_trace, Mapping):
        points = movement_trace.get("points", ())
        if not isinstance(points, list):
            raise ValueError("simulation movement_trace.points must be an array")
        for point in points:
            if not isinstance(point, Mapping):
                raise ValueError("simulation movement point must be an object")
            source_id = str(point.get("passenger_id"))
            anonymous_ids.setdefault(source_id, f"p{len(anonymous_ids) + 1:04d}")
            time_seconds = _finite_float(point.get("time_seconds"), "time_seconds")
            key = (source_id, round(time_seconds, 6))
            # The post-tick snapshot is authoritative when both sources share
            # an exact timestamp; internal points fill the walking intervals.
            movement_position = (
                _finite_float(point.get("x"), "x"),
                _finite_float(point.get("y"), "y"),
            )
            if key not in authoritative or snapshot_states.get(key) in _WALKING_STATES:
                authoritative[key] = movement_position

    anonymous_order = {anonymous_id: index for index, anonymous_id in enumerate(anonymous_ids.values())}
    observations = [
        {
            "id": anonymous_ids[source_id],
            "t": time_seconds,
            "x": position[0],
            "y": position[1],
        }
        for (source_id, time_seconds), position in sorted(
            authoritative.items(),
            key=lambda item: (
                item[0][1],
                anonymous_order[anonymous_ids[item[0][0]]],
            ),
        )
    ]

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(observations, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(observations)


def _finite_float(value: Any, label: str) -> float:
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{label} must be finite")
    return number
