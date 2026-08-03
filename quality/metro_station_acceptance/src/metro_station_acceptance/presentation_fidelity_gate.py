from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeGuard

from .trajectory_truth_inputs import TrajectoryTruthInputError


PRESENTATION_FIDELITY_GATE_SCHEMA_VERSION = "presentation_fidelity_gate_report.v1"

_WALKING_STATES = {
    "entering_station",
    "walking_to_vertical",
    "walking_to_platform",
    "walking_to_exit_gate",
    "walking_to_transfer",
}


@dataclass(frozen=True)
class _TrackAudit:
    source_point_count: int
    presentation_point_count: int
    visual_only_presentation_point_count: int
    source_issues: tuple[dict[str, object], ...]
    presentation_issues: tuple[dict[str, object], ...]
    source_samples: Counter[tuple[str, float, float, float, str]]


def analyze_presentation_fidelity(payload: object) -> dict[str, Any]:
    """Verify that display decoration is isolated from exported source samples."""

    if not isinstance(payload, Mapping):
        raise TrajectoryTruthInputError("presentation fidelity input must be an object")
    simulation_trace = payload.get("simulation_trace")
    if not isinstance(simulation_trace, Mapping):
        raise TrajectoryTruthInputError("simulation_trace is required")
    metadata = simulation_trace.get("metadata")
    if not isinstance(metadata, Mapping):
        raise TrajectoryTruthInputError("simulation_trace.metadata is required")
    replay_fidelity = metadata.get("replay_fidelity")
    if not isinstance(replay_fidelity, Mapping):
        raise TrajectoryTruthInputError("simulation_trace.metadata.replay_fidelity is required")
    replay_package = payload.get("replay_package")
    replay_metadata = replay_package.get("metadata") if isinstance(replay_package, Mapping) else None
    agents = payload.get("agents")
    if not _is_sequence(agents):
        raise TrajectoryTruthInputError("top-level agents array is required")

    coordinate_transform = _coordinate_transform(replay_fidelity)
    transform_id = str(coordinate_transform["id"])
    audit = _audit_tracks(agents, transform_id=transform_id)
    authoritative_samples = _authoritative_source_samples(
        simulation_trace,
        coordinate_transform=coordinate_transform,
    )
    missing_source = authoritative_samples - audit.source_samples
    extra_source = audit.source_samples - authoritative_samples
    contract_issues: list[dict[str, object]] = []
    expected_contract = {
        "position_authority": "simulation_trace.snapshots",
        "walking_position_authority": "simulation_trace.movement_trace",
        "visual_tracks_authoritative": False,
        "visual_track_source_points_field": "points",
        "visual_track_presentation_points_field": "presentation_points",
        "facility_overlays_modify_source_points": False,
        "renderer_track_field": "points",
    }
    for key, expected in expected_contract.items():
        if replay_fidelity.get(key) != expected:
            contract_issues.append(
                {"field": key, "expected": expected, "observed": replay_fidelity.get(key)}
            )
    if not isinstance(replay_metadata, Mapping) or (
        replay_metadata.get("visual_tracks_policy") != "presentation_only"
    ):
        contract_issues.append(
            {
                "field": "replay_package.metadata.visual_tracks_policy",
                "expected": "presentation_only",
                "observed": (
                    replay_metadata.get("visual_tracks_policy")
                    if isinstance(replay_metadata, Mapping)
                    else None
                ),
            }
        )

    checks = {
        "authority_contract_is_explicit": _count_check(contract_issues),
        "source_points_are_simulation_only": _count_check(list(audit.source_issues)),
        "presentation_points_are_well_formed": _count_check(
            list(audit.presentation_issues)
        ),
        "source_point_ledger_matches_authoritative_trace": _ledger_check(
            missing_source,
            extra_source,
        ),
    }
    failed = [name for name, check in checks.items() if check["status"] == "fail"]
    return {
        "schema_version": PRESENTATION_FIDELITY_GATE_SCHEMA_VERSION,
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "source": {
            "authority": [
                "simulation_trace.snapshots",
                "simulation_trace.movement_trace",
            ],
            "source_point_count": audit.source_point_count,
            "authoritative_observation_count": sum(authoritative_samples.values()),
            "presentation_point_count": audit.presentation_point_count,
            "visual_only_presentation_point_count": (
                audit.visual_only_presentation_point_count
            ),
            "visual_points_used_as_truth": 0,
        },
        "checks": checks,
        "summary": {"failed_checks": failed, "failed_check_count": len(failed)},
    }


def _audit_tracks(agents: Sequence[Any], *, transform_id: str) -> _TrackAudit:
    source_issues: list[dict[str, object]] = []
    presentation_issues: list[dict[str, object]] = []
    source_samples: Counter[tuple[str, float, float, float, str]] = Counter()
    source_count = 0
    presentation_count = 0
    visual_only_count = 0
    for agent_index, agent in enumerate(agents):
        if not isinstance(agent, Mapping):
            source_issues.append({"agent_index": agent_index, "reason": "agent_not_object"})
            continue
        agent_id = str(agent.get("id"))
        points = agent.get("points")
        if not _is_sequence(points):
            source_issues.append({"agent_id": agent_id, "reason": "points_not_array"})
            continue
        previous_time: float | None = None
        for point_index, point in enumerate(points):
            source_count += 1
            issue = _source_point_issue(point, previous_time, transform_id=transform_id)
            if issue is not None:
                source_issues.append(
                    {"agent_id": agent_id, "point_index": point_index, "reason": issue}
                )
                continue
            assert isinstance(point, Sequence)
            time_s = float(point[0])
            previous_time = time_s
            meta = point[9]
            assert isinstance(meta, Mapping)
            source_samples[
                (
                    agent_id,
                    round(time_s, 2),
                    round(float(point[1]), 2),
                    round(float(point[2]), 2),
                    str(meta.get("authority")),
                )
            ] += 1

        presentation = agent.get("presentation_points")
        if presentation is None:
            continue
        if not _is_sequence(presentation):
            presentation_issues.append(
                {"agent_id": agent_id, "reason": "presentation_points_not_array"}
            )
            continue
        previous_presentation_time: float | None = None
        for point_index, point in enumerate(presentation):
            presentation_count += 1
            issue = _track_point_shape_issue(point, previous_presentation_time)
            if issue is not None:
                presentation_issues.append(
                    {"agent_id": agent_id, "point_index": point_index, "reason": issue}
                )
                continue
            assert isinstance(point, Sequence)
            previous_presentation_time = float(point[0])
            meta = point[9]
            if isinstance(meta, Mapping) and bool(meta.get("visual_only")):
                visual_only_count += 1
    return _TrackAudit(
        source_point_count=source_count,
        presentation_point_count=presentation_count,
        visual_only_presentation_point_count=visual_only_count,
        source_issues=tuple(source_issues),
        presentation_issues=tuple(presentation_issues),
        source_samples=source_samples,
    )


def _source_point_issue(
    point: object,
    previous_time: float | None,
    *,
    transform_id: str,
) -> str | None:
    issue = _track_point_shape_issue(point, previous_time)
    if issue is not None:
        return issue
    assert isinstance(point, Sequence)
    meta = point[9]
    if not isinstance(meta, Mapping):
        return "source_meta_not_object"
    if bool(meta.get("visual_only")):
        return "source_point_is_visual_only"
    if meta.get("source") != "simulation":
        return "source_point_not_marked_simulation"
    if meta.get("authority") not in {
        "simulation_trace.snapshots",
        "simulation_trace.movement_trace",
    }:
        return "source_point_authority_invalid"
    if meta.get("coordinate_transform") != transform_id:
        return "source_point_transform_invalid"
    return None


def _track_point_shape_issue(point: object, previous_time: float | None) -> str | None:
    if not _is_sequence(point) or len(point) < 10:
        return "track_point_schema_invalid"
    try:
        time_s = float(point[0])
        float(point[1])
        float(point[2])
    except (TypeError, ValueError):
        return "track_point_time_or_position_not_numeric"
    if previous_time is not None and time_s <= previous_time:
        return "track_point_time_not_strictly_increasing"
    return None


def _authoritative_source_samples(
    simulation_trace: Mapping[str, Any],
    *,
    coordinate_transform: Mapping[str, object],
) -> Counter[tuple[str, float, float, float, str]]:
    snapshots = simulation_trace.get("snapshots")
    if not _is_sequence(snapshots):
        raise TrajectoryTruthInputError("simulation_trace.snapshots must be an array")
    result: Counter[tuple[str, float, float, float, str]] = Counter()
    snapshot_samples: dict[
        tuple[str, float],
        tuple[tuple[str, float, float, float, str], str],
    ] = {}
    for frame_index, frame in enumerate(snapshots):
        if not isinstance(frame, Mapping):
            raise TrajectoryTruthInputError(f"snapshot {frame_index} must be an object")
        try:
            time_s = round(float(frame["time_seconds"]), 2)
        except (KeyError, TypeError, ValueError) as exc:
            raise TrajectoryTruthInputError(
                f"snapshot {frame_index} has invalid time_seconds"
            ) from exc
        passengers = frame.get("passengers", [])
        if not _is_sequence(passengers):
            raise TrajectoryTruthInputError(f"snapshot {frame_index}.passengers must be an array")
        for passenger in passengers:
            if not isinstance(passenger, Mapping) or "id" not in passenger:
                raise TrajectoryTruthInputError(
                    f"snapshot {frame_index} passenger has no id"
                )
            agent_id = str(passenger["id"])
            x, y = _transform_position(
                passenger.get("x"),
                passenger.get("y"),
                coordinate_transform=coordinate_transform,
            )
            sample = (agent_id, time_s, x, y, "simulation_trace.snapshots")
            result[sample] += 1
            snapshot_samples[(agent_id, time_s)] = (
                sample,
                str(passenger.get("state", "")),
            )

    movement_trace = simulation_trace.get("movement_trace")
    if isinstance(movement_trace, Mapping):
        movement_points = movement_trace.get("points", ())
        if not _is_sequence(movement_points):
            raise TrajectoryTruthInputError("simulation_trace.movement_trace.points must be an array")
        for point_index, point in enumerate(movement_points):
            if not isinstance(point, Mapping):
                raise TrajectoryTruthInputError(
                    f"movement trace point {point_index} must be an object"
                )
            try:
                agent_id = str(point["passenger_id"])
                time_s = round(float(point["time_seconds"]), 2)
            except (KeyError, TypeError, ValueError) as exc:
                raise TrajectoryTruthInputError(
                    f"movement trace point {point_index} has invalid identity or time"
                ) from exc
            snapshot = snapshot_samples.get((agent_id, time_s))
            if snapshot is not None:
                snapshot_sample, snapshot_state = snapshot
                if snapshot_state not in _WALKING_STATES:
                    continue
                result[snapshot_sample] -= 1
                if result[snapshot_sample] <= 0:
                    del result[snapshot_sample]
            x, y = _transform_position(
                point.get("x"),
                point.get("y"),
                coordinate_transform=coordinate_transform,
            )
            result[(agent_id, time_s, x, y, "simulation_trace.movement_trace")] += 1
    return result


def _coordinate_transform(replay_fidelity: Mapping[str, Any]) -> Mapping[str, object]:
    value = replay_fidelity.get("visual_track_coordinate_transform")
    if not isinstance(value, Mapping):
        raise TrajectoryTruthInputError(
            "simulation_trace.metadata.replay_fidelity.visual_track_coordinate_transform "
            "is required"
        )
    if value.get("id") != "station_meters_to_canvas_pixels.v1":
        raise TrajectoryTruthInputError("unsupported visual track coordinate transform")
    if value.get("source_coordinates") != "station_model_meters":
        raise TrajectoryTruthInputError("visual track source coordinates must be meters")
    if value.get("target_coordinates") != "animation_canvas_pixels":
        raise TrajectoryTruthInputError("visual track target coordinates must be canvas pixels")
    for field in (
        "source_width_m",
        "source_height_m",
        "canvas_width_px",
        "canvas_height_px",
    ):
        try:
            number = float(value[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise TrajectoryTruthInputError(f"coordinate transform {field} must be numeric") from exc
        if number <= 0.0:
            raise TrajectoryTruthInputError(f"coordinate transform {field} must be positive")
    if value.get("clamp_to_canvas") is not True:
        raise TrajectoryTruthInputError("coordinate transform must clamp to canvas")
    if int(value.get("round_output_decimals", -1)) != 2:
        raise TrajectoryTruthInputError("coordinate transform must round output to 2 decimals")
    return value


def _transform_position(
    raw_x: object,
    raw_y: object,
    *,
    coordinate_transform: Mapping[str, object],
) -> tuple[float, float]:
    try:
        x = float(raw_x)  # type: ignore[arg-type]
        y = float(raw_y)  # type: ignore[arg-type]
        width = float(coordinate_transform["source_width_m"])
        height = float(coordinate_transform["source_height_m"])
        canvas_width = float(coordinate_transform["canvas_width_px"])
        canvas_height = float(coordinate_transform["canvas_height_px"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TrajectoryTruthInputError("authoritative position must be numeric") from exc
    return (
        round(max(0.0, min(canvas_width, x / width * canvas_width)), 2),
        round(max(0.0, min(canvas_height, y / height * canvas_height)), 2),
    )


def _count_check(examples: list[dict[str, object]]) -> dict[str, Any]:
    return {
        "status": "pass" if not examples else "fail",
        "hard": True,
        "count": len(examples),
        "threshold": {"maximum": 0},
        "examples": examples[:20],
    }


def _ledger_check(
    missing: Counter[tuple[str, float, float, float, str]],
    extra: Counter[tuple[str, float, float, float, str]],
) -> dict[str, Any]:
    examples = [
        {
            "agent_id": agent_id,
            "time_s": time_s,
            "x": x,
            "y": y,
            "authority": authority,
            "missing_count": count,
        }
        for (agent_id, time_s, x, y, authority), count in missing.items()
    ] + [
        {
            "agent_id": agent_id,
            "time_s": time_s,
            "x": x,
            "y": y,
            "authority": authority,
            "extra_count": count,
        }
        for (agent_id, time_s, x, y, authority), count in extra.items()
    ]
    return _count_check(examples)


def _is_sequence(value: object) -> TypeGuard[Sequence[Any]]:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
