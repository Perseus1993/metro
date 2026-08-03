"""Pure metric projections from versioned simulation snapshots."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .contracts import RunSummary
from .density import crowd_safety_metrics


def build_run_summary(
    *,
    role: str,
    case_id: str,
    seed: int,
    frames: Sequence[Mapping[str, Any]],
    clearance: Mapping[str, Any],
    density_radius_m: float,
    density_threshold_persons_m2: float | None,
) -> RunSummary:
    density = crowd_safety_metrics(
        frames,
        radius_m=density_radius_m,
        tick_seconds=_tick_seconds(frames),
        threshold_persons_m2=density_threshold_persons_m2,
    )
    gate_queue, vertical_queue = _peak_queues(frames)
    remaining = _integer(clearance.get("remaining_agents"))
    return RunSummary(
        role=role,
        case_id=case_id,
        seed=seed,
        status="ok",
        cleared=bool(clearance.get("cleared")),
        right_censored=bool(clearance.get("right_censored")),
        clearance_time_s=_optional_float(clearance.get("clearance_time_s")),
        remaining_agents=remaining,
        total_agents=_integer(clearance.get("total_agents")),
        peak_density_persons_m2=_metric_float(density, "peak_local_density_persons_m2"),
        density_exposure_person_s=_metric_float(density, "density_exposure_person_seconds"),
        density_duration_above_threshold_s=_metric_float(
            density, "duration_above_density_threshold_seconds"
        ),
        max_gate_queue=gate_queue,
        max_vertical_queue=vertical_queue,
        stuck_agents=remaining,
        peak_density_location={
            "time_seconds": density["peak_local_density_time_seconds"],
            "level_id": density["peak_local_density_level_id"],
            "x": density["peak_local_density_x"],
            "y": density["peak_local_density_y"],
            "passenger_id": density["peak_local_density_passenger_id"],
        },
        top_bottleneck=_top_bottleneck(frames),
        control_events=_control_events(frames),
    )


def _peak_queues(frames: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    metrics = [frame.get("metrics", {}) for frame in frames]
    gate = max((_integer(item.get("gate_queue_persons")) for item in metrics), default=0)
    vertical = max((_integer(item.get("vertical_queue_persons")) for item in metrics), default=0)
    return gate, vertical


def _top_bottleneck(frames: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for frame in frames:
        for facility in frame.get("facilities", []):
            if not isinstance(facility, Mapping):
                continue
            load = _integer(facility.get("queue_persons")) + _integer(
                facility.get("active_persons")
            )
            capacity = max(1, _integer(facility.get("queue_capacity"), 1))
            pressure = load / capacity
            if best is not None and pressure <= float(best["pressure"]):
                continue
            best = {
                "facility_id": facility.get("id"),
                "label": facility.get("label"),
                "time_seconds": frame.get("time_seconds"),
                "load_persons": load,
                "capacity": capacity,
                "pressure": round(pressure, 6),
            }
    return best


def _control_events(frames: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str]] = set()
    for frame in frames:
        for event in frame.get("control_events", []):
            if not isinstance(event, Mapping):
                continue
            key = (
                str(event.get("event_id", "")),
                float(event.get("applied_seconds", 0.0) or 0.0),
                str(event.get("status", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(dict(event))
    return tuple(events)


def _tick_seconds(frames: Sequence[Mapping[str, Any]]) -> float:
    if len(frames) < 2:
        return 1.0
    return max(
        0.001, float(frames[1].get("time_seconds", 0)) - float(frames[0].get("time_seconds", 0))
    )


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_float(
    metrics: Mapping[str, int | float | str | None],
    key: str,
) -> float:
    value = metrics.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"metric {key!r} must be numeric")
    return float(value)
