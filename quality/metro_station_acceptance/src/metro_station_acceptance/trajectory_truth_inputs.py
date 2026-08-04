from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeGuard, cast


class TrajectoryTruthInputError(ValueError):
    """Raised when presentation data is offered as simulation truth."""


@dataclass(frozen=True)
class TruthObservation:
    agent_id: str
    time_s: float
    x: float
    y: float
    source_index: int
    level_id: str | None = None


@dataclass(frozen=True)
class TruthInput:
    source_kind: str
    coordinate_unit: str | None
    observations: tuple[TruthObservation, ...]
    snapshot_count: int


def extract_truth_input(
    payload: object,
    *,
    coordinate_unit: str | None = None,
) -> TruthInput:
    """Extract authoritative observations without accepting presentation tracks."""

    if isinstance(payload, Mapping):
        return _extract_mapping(payload, coordinate_unit=coordinate_unit)
    if _is_sequence(payload):
        return _extract_sequence(payload, coordinate_unit=coordinate_unit)
    raise TrajectoryTruthInputError("input must be a JSON object or array")


def _extract_mapping(
    payload: Mapping[str, Any],
    *,
    coordinate_unit: str | None,
) -> TruthInput:
    trace = payload.get("simulation_trace")
    if isinstance(trace, Mapping):
        return _extract_simulation_trace(
            trace,
            source_kind="replay.simulation_trace",
            coordinate_unit=coordinate_unit,
        )

    schema_version = str(payload.get("schema_version", ""))
    if schema_version.startswith("simulation_trace.") or "snapshots" in payload:
        return _extract_simulation_trace(
            payload,
            source_kind="simulation_trace",
            coordinate_unit=coordinate_unit,
        )

    if _contains_presentation_tracks(payload):
        raise TrajectoryTruthInputError(
            "visual_tracks/agents are presentation data; provide simulation_trace.snapshots"
        )

    if "points" in payload:
        points = payload.get("points")
        if not _is_sequence(points):
            raise TrajectoryTruthInputError("normalized 'points' must be an array")
        unit = coordinate_unit or _optional_text(payload.get("coordinate_unit"))
        return _extract_normalized(points, coordinate_unit=unit)
    raise TrajectoryTruthInputError(
        "expected simulation_trace, snapshots, or normalized points with id/t/x/y"
    )


def _extract_sequence(
    values: Sequence[Any],
    *,
    coordinate_unit: str | None,
) -> TruthInput:
    first = next((item for item in values if isinstance(item, Mapping)), None)
    if first is None:
        raise TrajectoryTruthInputError("input array contains no records")
    if "passengers" in first or "time_seconds" in first:
        return _extract_snapshots(
            values,
            source_kind="simulation_trace.snapshots",
            coordinate_unit=coordinate_unit or "m",
        )
    return _extract_normalized(values, coordinate_unit=coordinate_unit)


def _extract_simulation_trace(
    trace: Mapping[str, Any],
    *,
    source_kind: str,
    coordinate_unit: str | None,
) -> TruthInput:
    if _contains_presentation_tracks(trace):
        raise TrajectoryTruthInputError(
            "simulation_trace must not contain visual_tracks/visual_only samples"
        )
    snapshots = trace.get("snapshots")
    if not _is_sequence(snapshots):
        raise TrajectoryTruthInputError("simulation_trace.snapshots must be an array")
    return _extract_snapshots(
        snapshots,
        source_kind=source_kind,
        coordinate_unit=coordinate_unit or "m",
    )


def _extract_snapshots(
    snapshots: Sequence[Any],
    *,
    source_kind: str,
    coordinate_unit: str | None,
) -> TruthInput:
    observations: list[TruthObservation] = []
    for frame_index, frame in enumerate(snapshots):
        if not isinstance(frame, Mapping):
            raise TrajectoryTruthInputError(f"snapshot {frame_index} must be an object")
        if "time_seconds" not in frame:
            raise TrajectoryTruthInputError(f"snapshot {frame_index} has no time_seconds")
        passengers = frame.get("passengers", [])
        if not _is_sequence(passengers):
            raise TrajectoryTruthInputError(f"snapshot {frame_index}.passengers must be an array")
        for passenger in passengers:
            observations.append(
                _snapshot_observation(passenger, frame["time_seconds"], frame_index)
            )
    return _finish_input(source_kind, coordinate_unit, observations, len(snapshots))


def _snapshot_observation(
    passenger: object,
    time_value: object,
    source_index: int,
) -> TruthObservation:
    if not isinstance(passenger, Mapping):
        raise TrajectoryTruthInputError(f"snapshot {source_index} passenger must be an object")
    _reject_visual_only(passenger, f"snapshot {source_index} passenger")
    return _observation(passenger, time_value=time_value, time_key="time_seconds", source_index=source_index)


def _extract_normalized(
    points: Sequence[Any],
    *,
    coordinate_unit: str | None,
) -> TruthInput:
    observations: list[TruthObservation] = []
    for index, point in enumerate(points):
        if not isinstance(point, Mapping):
            raise TrajectoryTruthInputError(f"normalized point {index} must be an object")
        _reject_visual_only(point, f"normalized point {index}")
        observations.append(_observation(point, time_value=point.get("t"), time_key="t", source_index=index))
    return _finish_input("normalized.id_t_x_y", coordinate_unit, observations, 0)


def _observation(
    record: Mapping[str, Any],
    *,
    time_value: object,
    time_key: str,
    source_index: int,
) -> TruthObservation:
    missing = [key for key in ("id", "x", "y") if key not in record]
    if time_value is None:
        missing.append(time_key)
    if missing:
        raise TrajectoryTruthInputError(
            f"record {source_index} is missing required fields: {', '.join(missing)}"
        )
    try:
        return TruthObservation(
            agent_id=str(record["id"]),
            time_s=float(cast(Any, time_value)),
            x=float(record["x"]),
            y=float(record["y"]),
            source_index=source_index,
            level_id=_observation_level(record),
        )
    except (TypeError, ValueError) as exc:
        raise TrajectoryTruthInputError(
            f"record {source_index} time/x/y must be numeric"
        ) from exc


def _finish_input(
    source_kind: str,
    coordinate_unit: str | None,
    observations: list[TruthObservation],
    snapshot_count: int,
) -> TruthInput:
    if not observations:
        raise TrajectoryTruthInputError("truth input contains no passenger observations")
    return TruthInput(
        source_kind=source_kind,
        coordinate_unit=coordinate_unit,
        observations=tuple(observations),
        snapshot_count=snapshot_count,
    )


def _reject_visual_only(record: Mapping[str, Any], label: str) -> None:
    meta = record.get("meta")
    if bool(record.get("visual_only")) or (
        isinstance(meta, Mapping) and bool(meta.get("visual_only"))
    ):
        raise TrajectoryTruthInputError(f"{label} is visual_only and cannot be truth evidence")


def _contains_presentation_tracks(payload: Mapping[str, Any]) -> bool:
    return any(key in payload for key in ("visual_tracks", "agents", "tracks"))


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _observation_level(record: Mapping[str, Any]) -> str | None:
    for key in ("physical_layer_id", "level", "level_id", "current_level_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _is_sequence(value: object) -> TypeGuard[Sequence[Any]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
