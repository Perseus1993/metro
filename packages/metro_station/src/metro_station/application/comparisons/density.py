"""Crowd-density projections from versioned simulation snapshots."""

from __future__ import annotations

from collections import defaultdict
from math import floor, isfinite, pi
from typing import Any, Iterable, Mapping


def crowd_safety_metrics(
    frames: Iterable[Mapping[str, Any]],
    *,
    radius_m: float,
    tick_seconds: float,
    threshold_persons_m2: float | None = None,
) -> dict[str, int | float | str | None]:
    radius = _positive("radius_m", radius_m)
    tick = _positive("tick_seconds", tick_seconds)
    threshold = _optional_positive("threshold_persons_m2", threshold_persons_m2)
    peak_density = 0.0
    peak_time = 0.0
    exposure = 0.0
    frames_above_threshold = 0
    peak_passenger: Mapping[str, Any] = {}

    for frame in frames:
        passengers = [item for item in frame.get("passengers", []) if isinstance(item, Mapping)]
        densities = _local_densities(passengers, radius)
        frame_peak = max(densities, default=0.0)
        if frame_peak > peak_density:
            peak_density = frame_peak
            peak_time = float(frame.get("time_seconds", 0.0) or 0.0)
            peak_passenger = passengers[densities.index(frame_peak)]
        if threshold is None:
            continue
        if any(density > threshold for density in densities):
            frames_above_threshold += 1
        exposure += sum(
            max(0, _integer(passenger.get("n"), 1)) * tick
            for passenger, density in zip(passengers, densities, strict=True)
            if density > threshold
        )

    return {
        "density_radius_m": round(radius, 6),
        "density_threshold_persons_m2": threshold,
        "peak_local_density_persons_m2": round(peak_density, 6),
        "peak_local_density_time_seconds": round(peak_time, 6),
        "density_exposure_person_seconds": round(exposure, 6),
        "frames_above_density_threshold": frames_above_threshold,
        "duration_above_density_threshold_seconds": round(frames_above_threshold * tick, 6),
        "peak_local_density_level_id": peak_passenger.get("current_level_id"),
        "peak_local_density_x": _optional_float(peak_passenger.get("x")),
        "peak_local_density_y": _optional_float(peak_passenger.get("y")),
        "peak_local_density_passenger_id": peak_passenger.get("id"),
    }


def _local_densities(passengers: list[Mapping[str, Any]], radius: float) -> list[float]:
    buckets: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    positions: list[tuple[str, float, float, int]] = []
    for index, passenger in enumerate(passengers):
        level = str(passenger.get("current_level_id") or "unknown")
        x = float(passenger.get("x", 0.0) or 0.0)
        y = float(passenger.get("y", 0.0) or 0.0)
        persons = max(0, _integer(passenger.get("n"), 1))
        positions.append((level, x, y, persons))
        buckets[(level, floor(x / radius), floor(y / radius))].append(index)
    area = pi * radius * radius
    radius_squared = radius * radius
    return [
        sum(
            positions[index][3]
            for cell_x in range(floor(x / radius) - 1, floor(x / radius) + 2)
            for cell_y in range(floor(y / radius) - 1, floor(y / radius) + 2)
            for index in buckets.get((level, cell_x, cell_y), ())
            if (positions[index][1] - x) ** 2 + (positions[index][2] - y) ** 2 <= radius_squared
        )
        / area
        for level, x, y, _persons in positions
    ]


def _positive(name: str, value: float) -> float:
    parsed = float(value)
    if not isfinite(parsed) or parsed <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return parsed


def _optional_positive(name: str, value: float | None) -> float | None:
    return None if value is None else _positive(name, value)


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
