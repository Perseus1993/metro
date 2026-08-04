from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_MOVEMENT_AUTHORITIES = frozenset({"jupedsim", "jupedsim_committed_walk"})
_FACILITY_MOTION_AUTHORITIES = frozenset({"facility_process_model"})
_AUTHORITY_HANDOFF_EPSILON_M = 0.001
_SNAPSHOT_PRECEDENCE = 0
_FACILITY_PRECEDENCE = 1
_MOVEMENT_PRECEDENCE = 2


def export_anonymized_xy_observations(
    replay_path: str | Path,
    output_path: str | Path,
) -> int:
    """Export only anonymous ``id,t,x,y`` observations from simulation truth."""

    source = json.loads(Path(replay_path).read_text(encoding="utf-8"))
    observations = anonymized_xy_observations(source)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(observations, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(observations)


def anonymized_xy_observations(source: object) -> list[dict[str, object]]:
    """Return the same blind evidence without requiring an intermediate file."""

    if not isinstance(source, Mapping):
        raise ValueError("input must be a replay object")
    trace = source.get("simulation_trace")
    if not isinstance(trace, Mapping) or trace.get("schema_version") != "simulation_trace.v1":
        raise ValueError("input must contain simulation_trace.v1 authoritative snapshots")

    anonymous_ids: dict[str, str] = {}
    anonymous_levels: dict[str, str] = {}
    authoritative: list[tuple[str, float, float, float, str | None, int, int]] = []
    source_index = 0
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
            _reject_visual_only(passenger, "simulation passenger")
            source_id = str(passenger.get("id"))
            anonymous_ids.setdefault(
                source_id,
                f"p{len(anonymous_ids) + 1:04d}",
            )
            level = _anonymous_level(
                passenger.get(
                    "physical_layer_id",
                    passenger.get("current_level_id", passenger.get("level_id")),
                ),
                anonymous_levels,
            )
            authoritative.append(
                (
                    source_id,
                    round(time_seconds, 6),
                    _finite_float(passenger.get("x"), "x"),
                    _finite_float(passenger.get("y"), "y"),
                    level,
                    source_index,
                    _SNAPSHOT_PRECEDENCE,
                )
            )
            source_index += 1

    movement_trace = trace.get("movement_trace")
    if isinstance(movement_trace, Mapping):
        points = movement_trace.get("points", ())
        if not isinstance(points, list):
            raise ValueError("simulation movement_trace.points must be an array")
        metadata = movement_trace.get("metadata")
        if points:
            if not isinstance(metadata, Mapping):
                raise ValueError("movement_trace metadata is required for blind truth export")
            if bool(metadata.get("visual_only")):
                raise ValueError("visual_only movement_trace cannot be blind truth input")
            authority = str(metadata.get("authority", ""))
            if authority not in _MOVEMENT_AUTHORITIES:
                raise ValueError(
                    f"movement_trace authority {authority!r} is not JuPedSim truth"
                )
        for point in points:
            if not isinstance(point, Mapping):
                raise ValueError("simulation movement point must be an object")
            _reject_visual_only(point, "simulation movement point")
            point_authority = str(point.get("authority", authority))
            if point_authority not in _MOVEMENT_AUTHORITIES:
                raise ValueError(
                    f"simulation movement point authority {point_authority!r} "
                    "is not JuPedSim truth"
                )
            source_id = str(point.get("passenger_id"))
            anonymous_ids.setdefault(source_id, f"p{len(anonymous_ids) + 1:04d}")
            level = _anonymous_level(point.get("level_id"), anonymous_levels)
            time_seconds = _finite_float(point.get("time_seconds"), "time_seconds")
            # Authority-boundary copies are reconciled after all three truth
            # ledgers have been collected. Material disagreements are kept.
            authoritative.append(
                (
                    source_id,
                    round(time_seconds, 6),
                    _finite_float(point.get("x"), "x"),
                    _finite_float(point.get("y"), "y"),
                    level,
                    source_index,
                    _MOVEMENT_PRECEDENCE,
                )
            )
            source_index += 1

    facility_motion_trace = trace.get("facility_motion_trace")
    if isinstance(facility_motion_trace, Mapping):
        points = facility_motion_trace.get("points", ())
        if not isinstance(points, list):
            raise ValueError("simulation facility_motion_trace.points must be an array")
        metadata = facility_motion_trace.get("metadata")
        authority = ""
        if points:
            if not isinstance(metadata, Mapping):
                raise ValueError(
                    "facility_motion_trace metadata is required for blind truth export"
                )
            if bool(metadata.get("visual_only")):
                raise ValueError(
                    "visual_only facility_motion_trace cannot be blind truth input"
                )
            authority = str(metadata.get("authority", ""))
            if authority not in _FACILITY_MOTION_AUTHORITIES:
                raise ValueError(
                    f"facility motion authority {authority!r} is not process truth"
                )
        for point in points:
            if not isinstance(point, Mapping):
                raise ValueError("simulation facility motion point must be an object")
            _reject_visual_only(point, "simulation facility motion point")
            point_authority = str(point.get("authority", authority))
            if point_authority not in _FACILITY_MOTION_AUTHORITIES:
                raise ValueError(
                    f"simulation facility motion point authority {point_authority!r} "
                    "is not process truth"
                )
            source_id = str(point.get("passenger_id"))
            anonymous_ids.setdefault(source_id, f"p{len(anonymous_ids) + 1:04d}")
            level = _anonymous_level(point.get("level_id"), anonymous_levels)
            time_seconds = _finite_float(point.get("time_seconds"), "time_seconds")
            authoritative.append(
                (
                    source_id,
                    round(time_seconds, 6),
                    _finite_float(point.get("x"), "x"),
                    _finite_float(point.get("y"), "y"),
                    level,
                    source_index,
                    _FACILITY_PRECEDENCE,
                )
            )
            source_index += 1

    authoritative = _reconcile_authority_handoffs(authoritative)
    anonymous_order = {
        anonymous_id: index for index, anonymous_id in enumerate(anonymous_ids.values())
    }
    return [
        {
            "id": anonymous_ids[source_id],
            "t": time_seconds,
            "x": x,
            "y": y,
            **({"level": level} if level is not None else {}),
        }
        for source_id, time_seconds, x, y, level, _source_index, _precedence in sorted(
            authoritative,
            key=lambda item: (
                item[1],
                anonymous_order[anonymous_ids[item[0]]],
                item[5],
            ),
        )
    ]


def _reconcile_authority_handoffs(
    observations: list[tuple[str, float, float, float, str | None, int, int]],
) -> list[tuple[str, float, float, float, str | None, int, int]]:
    """Collapse only spatially equivalent records at an authority boundary.

    Landing, connector, and coarse snapshot ledgers intentionally share an
    inclusive boundary sample.  Floating-point serialization can make those
    copies differ by fractions of a millimetre and their logical layer tokens
    differ by design.  They are one physical observation, so retain the
    highest-rate collision authority.  Material same-time disagreements stay
    untouched and remain visible to the blind hard gate.
    """

    grouped: dict[
        tuple[str, float],
        list[tuple[str, float, float, float, str | None, int, int]],
    ] = {}
    for observation in observations:
        grouped.setdefault((observation[0], observation[1]), []).append(observation)

    reconciled: list[tuple[str, float, float, float, str | None, int, int]] = []
    for records in grouped.values():
        if len(records) <= 1 or any(
            ((left[2] - right[2]) ** 2 + (left[3] - right[3]) ** 2) ** 0.5
            > _AUTHORITY_HANDOFF_EPSILON_M
            for index, left in enumerate(records)
            for right in records[index + 1 :]
        ):
            reconciled.extend(records)
            continue
        reconciled.append(max(records, key=lambda record: (record[6], record[5])))
    return reconciled


def _anonymous_level(
    value: object,
    anonymous_levels: dict[str, str],
) -> str | None:
    if value is None:
        return None
    source_level = str(value)
    anonymous_levels.setdefault(
        source_level,
        f"l{len(anonymous_levels) + 1:04d}",
    )
    return anonymous_levels[source_level]


def _finite_float(value: Any, label: str) -> float:
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{label} must be finite")
    return number


def _reject_visual_only(value: Mapping[str, Any], label: str) -> None:
    metadata = value.get("meta")
    if bool(value.get("visual_only")) or (
        isinstance(metadata, Mapping) and bool(metadata.get("visual_only"))
    ):
        raise ValueError(f"{label} is visual_only and cannot be blind truth input")
