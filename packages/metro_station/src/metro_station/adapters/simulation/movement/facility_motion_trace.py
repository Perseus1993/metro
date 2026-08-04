from __future__ import annotations

from collections import defaultdict
from math import ceil, isfinite
from typing import Any, Mapping


FACILITY_MOTION_TRACE_SCHEMA_VERSION = "facility_motion_trace.v1"


class FacilityMotionTraceRecorder:
    """Record process-owned body positions independently of Mesa snapshots."""

    def __init__(self, *, sample_interval_seconds: float) -> None:
        self.sample_interval_seconds = float(sample_interval_seconds)
        if (
            not isfinite(self.sample_interval_seconds)
            or self.sample_interval_seconds <= 0.0
        ):
            raise ValueError("facility motion sample interval must be finite and positive")
        self._points: list[dict[str, object]] = []
        self._covered_phases: set[str] = set()
        self._seen: set[tuple[int, float, str]] = set()
        self._sample_indices: defaultdict[tuple[str, int], int] = defaultdict(int)

    def sample_times(self, start_time_s: float, end_time_s: float) -> tuple[float, ...]:
        start = float(start_time_s)
        end = float(end_time_s)
        if end < start - 1e-9:
            raise ValueError("facility motion interval cannot regress")
        interval = self.sample_interval_seconds
        first_index = ceil((start - 1e-9) / interval)
        # Phase boundaries are authoritative hand-off coordinates.  Preserve
        # them even when they do not land on the global sample grid; the grid
        # points between them still bound every gap by the configured interval.
        values: set[float] = {round(start, 6), round(end, 6)}
        index = first_index
        while index * interval <= end + 1e-9:
            time_s = round(index * interval, 6)
            if time_s >= start - 1e-9:
                values.add(time_s)
            index += 1
        return tuple(sorted(values))

    def record_positions(
        self,
        *,
        time_seconds: float,
        level_id: str,
        phase: str,
        episode_id: str,
        positions: Mapping[int, tuple[float, float]],
    ) -> None:
        time_s = round(float(time_seconds), 6)
        self._covered_phases.add(str(phase))
        for passenger_id, position in sorted(positions.items()):
            key = (int(passenger_id), time_s, str(episode_id))
            if key in self._seen:
                continue
            self._seen.add(key)
            index_key = (str(episode_id), int(passenger_id))
            sample_index = self._sample_indices[index_key]
            self._sample_indices[index_key] = sample_index + 1
            self._points.append(
                {
                    "passenger_id": int(passenger_id),
                    "time_seconds": time_s,
                    # Snapshot truth is serialized to millimetres.  Use the
                    # same boundary precision so equal-time authorities are
                    # byte-for-byte coordinate consistent.
                    "x": round(float(position[0]), 3),
                    "y": round(float(position[1]), 3),
                    "level_id": str(level_id),
                    "phase": str(phase),
                    "episode_id": str(episode_id),
                    "sample_index": sample_index,
                    "authority": "facility_process_model",
                    "visual_only": False,
                }
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FACILITY_MOTION_TRACE_SCHEMA_VERSION,
            "metadata": {
                "authority": "facility_process_model",
                "coordinates": "station_model_meters",
                "sample_interval_seconds": self.sample_interval_seconds,
                "visual_only": False,
                "coverage": sorted(self._covered_phases),
            },
            "points": sorted(
                self._points,
                key=lambda point: (
                    float(point["time_seconds"]),
                    int(point["passenger_id"]),
                    str(point["episode_id"]),
                    int(point["sample_index"]),
                ),
            ),
        }


def facility_motion_trace_from_any(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        return {
            "schema_version": FACILITY_MOTION_TRACE_SCHEMA_VERSION,
            "metadata": {
                "authority": "facility_process_model",
                "coordinates": "station_model_meters",
                "visual_only": False,
                "coverage": [],
                "reason": "not_supplied",
            },
            "points": [],
        }
    if str(value.get("schema_version", "")) != FACILITY_MOTION_TRACE_SCHEMA_VERSION:
        raise ValueError("facility motion trace must use facility_motion_trace.v1")
    points = value.get("points")
    if not isinstance(points, list):
        raise TypeError("facility_motion_trace.points must be an array")
    return {
        "schema_version": FACILITY_MOTION_TRACE_SCHEMA_VERSION,
        "metadata": dict(value.get("metadata", {})),
        "points": [dict(point) for point in points],
    }


__all__ = ["FacilityMotionTraceRecorder", "facility_motion_trace_from_any"]
