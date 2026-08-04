from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any, Iterable, Mapping


MOVEMENT_TRACE_SCHEMA_VERSION = "movement_trace.v1"


@dataclass(frozen=True)
class MovementTracePoint:
    passenger_id: int
    time_seconds: float
    x: float
    y: float
    level_id: str | None
    episode_id: str
    sample_index: int
    authority: str = "jupedsim"
    phase: str = "walking"

    def __post_init__(self) -> None:
        if not isfinite(self.time_seconds) or self.time_seconds < 0.0:
            raise ValueError(f"time_seconds must be finite and >= 0; got {self.time_seconds!r}")
        if not isfinite(self.x) or not isfinite(self.y):
            raise ValueError(f"movement coordinates must be finite; got {(self.x, self.y)!r}")
        if not self.episode_id:
            raise ValueError("episode_id must be non-empty")
        if self.sample_index < 0:
            raise ValueError("sample_index must be >= 0")

    def as_dict(self) -> dict[str, object]:
        return {
            "passenger_id": int(self.passenger_id),
            "time_seconds": round(float(self.time_seconds), 6),
            "x": float(self.x),
            "y": float(self.y),
            "level_id": self.level_id,
            "episode_id": self.episode_id,
            "sample_index": int(self.sample_index),
            "authority": self.authority,
            "phase": self.phase,
        }


class MovementTraceRecorder:
    """Collect monotone samples from the configured walking authority."""

    def __init__(
        self,
        *,
        sample_interval_seconds: float,
        integration_dt_seconds: float,
        authority: str = "jupedsim",
    ) -> None:
        self.sample_interval_seconds = float(sample_interval_seconds)
        self.integration_dt_seconds = float(integration_dt_seconds)
        self.authority = str(authority)
        if not isfinite(self.sample_interval_seconds) or self.sample_interval_seconds <= 0.0:
            raise ValueError("sample_interval_seconds must be finite and > 0")
        if not isfinite(self.integration_dt_seconds) or self.integration_dt_seconds <= 0.0:
            raise ValueError("integration_dt_seconds must be finite and > 0")
        ratio = self.sample_interval_seconds / self.integration_dt_seconds
        rounded = round(ratio)
        if not isclose(ratio, rounded, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                "movement trace interval must be an integer multiple of JuPedSim dt; "
                f"got {self.sample_interval_seconds} / {self.integration_dt_seconds}"
            )
        self.every_nth_iteration = max(1, int(rounded))
        self._points: list[MovementTracePoint] = []
        self._last_time_by_episode: dict[str, float] = {}
        self._level_by_episode: dict[str, str | None] = {}
        self._sample_index_by_episode: dict[str, int] = {}
        self._active_episode_by_passenger: dict[int, str] = {}
        self._closed_episode_ids: set[str] = set()

    @property
    def points(self) -> tuple[MovementTracePoint, ...]:
        return tuple(self._points)

    def record_positions(
        self,
        *,
        time_seconds: float,
        level_id: str | None,
        positions: Mapping[int, tuple[float, float]],
        episode_ids: Mapping[int, str],
        phases_by_passenger: Mapping[int, str] | None = None,
    ) -> None:
        for passenger_id, position in sorted(positions.items()):
            passenger_id = int(passenger_id)
            episode_id = str(episode_ids.get(passenger_id, ""))
            if not episode_id:
                raise ValueError(
                    f"movement sample for passenger {passenger_id} has no session episode id"
                )
            active_episode = self._active_episode_by_passenger.get(passenger_id)
            if active_episode != episode_id:
                if episode_id in self._closed_episode_ids:
                    raise ValueError(f"closed movement episode {episode_id!r} cannot be resumed")
                if active_episode is not None:
                    self._closed_episode_ids.add(active_episode)
                self._active_episode_by_passenger[passenger_id] = episode_id
            last_time = self._last_time_by_episode.get(episode_id)
            if last_time is not None and time_seconds <= last_time + 1e-9:
                continue
            previous_level = self._level_by_episode.get(episode_id, level_id)
            if previous_level != level_id:
                raise ValueError(
                    f"movement episode {episode_id!r} changed level from "
                    f"{previous_level!r} to {level_id!r}"
                )
            sample_index = self._sample_index_by_episode.get(episode_id, -1) + 1
            point = MovementTracePoint(
                passenger_id=passenger_id,
                time_seconds=float(time_seconds),
                x=float(position[0]),
                y=float(position[1]),
                level_id=level_id,
                episode_id=episode_id,
                sample_index=sample_index,
                authority=self.authority,
                phase=str(
                    (phases_by_passenger or {}).get(passenger_id, "walking")
                ),
            )
            self._points.append(point)
            self._last_time_by_episode[episode_id] = float(time_seconds)
            self._level_by_episode[episode_id] = level_id
            self._sample_index_by_episode[episode_id] = sample_index

    def discard_passenger_samples_after(
        self,
        passenger_id: int,
        *,
        time_seconds: float,
    ) -> None:
        """Rollback an uncommitted backend proposal for one passenger."""

        passenger_id = int(passenger_id)
        kept = [
            point
            for point in self._points
            if not (
                point.passenger_id == passenger_id
                and point.time_seconds > float(time_seconds) + 1e-9
            )
        ]
        if len(kept) == len(self._points):
            return
        self._points = kept
        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        self._last_time_by_episode.clear()
        self._level_by_episode.clear()
        self._sample_index_by_episode.clear()
        self._active_episode_by_passenger.clear()
        self._closed_episode_ids.clear()
        for point in self._points:
            active = self._active_episode_by_passenger.get(point.passenger_id)
            if active is not None and active != point.episode_id:
                self._closed_episode_ids.add(active)
            self._active_episode_by_passenger[point.passenger_id] = point.episode_id
            self._last_time_by_episode[point.episode_id] = point.time_seconds
            self._level_by_episode[point.episode_id] = point.level_id
            self._sample_index_by_episode[point.episode_id] = point.sample_index

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MOVEMENT_TRACE_SCHEMA_VERSION,
            "metadata": {
                "authority": self.authority,
                "coverage": [
                    "walking",
                    "passive_layout",
                    "same_floor_facility",
                    "elevator_boarding",
                    "elevator_unloading",
                ],
                "coordinates": "station_model_meters",
                "sample_interval_seconds": self.sample_interval_seconds,
                "integration_dt_seconds": self.integration_dt_seconds,
                "every_nth_iteration": self.every_nth_iteration,
                "episode_contract": "explicit_jupedsim_session_lifecycle",
                "visual_only": False,
            },
            "points": [point.as_dict() for point in self._points],
        }


def empty_movement_trace(*, reason: str) -> dict[str, Any]:
    return {
        "schema_version": MOVEMENT_TRACE_SCHEMA_VERSION,
        "metadata": {
            "authority": "jupedsim",
            "coverage": [
                "walking",
                "passive_layout",
                "same_floor_facility",
                "elevator_boarding",
                "elevator_unloading",
            ],
            "visual_only": False,
            "enabled": False,
            "reason": str(reason),
        },
        "points": [],
    }


def movement_trace_from_any(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return empty_movement_trace(reason="not_supplied")
    points = value.get("points")
    if not isinstance(points, Iterable) or isinstance(points, str | bytes | Mapping):
        raise TypeError("movement_trace.points must be an iterable of point mappings")
    return dict(value)
