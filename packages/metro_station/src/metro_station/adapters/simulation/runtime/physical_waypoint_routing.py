from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from shapely.geometry import LineString, Point as ShapelyPoint

from ..station.geometry import project_to_safe_point


Point = tuple[float, float]


class PhysicalRouteUnreachableError(RuntimeError):
    """A semantic destination cannot be connected inside one walking domain."""


@dataclass(frozen=True)
class FacilityPortals:
    """Physical hand-off points around one facility service process."""

    approach: Point
    entry: Point
    exit: Point
    entry_level_id: str | None
    exit_level_id: str | None


class PhysicalWaypointRouter:
    """Resolve semantic anchors to JuPedSim navigation-mesh waypoints."""

    def __init__(self) -> None:
        self._engines: dict[tuple[str | None, bytes], Any] = {}

    def clear(self) -> None:
        self._engines.clear()

    def route(
        self,
        walkable_area: Any,
        start: Point,
        anchors: tuple[Point, ...],
        *,
        level_id: str | None,
        clearance: float,
    ) -> tuple[Point, ...]:
        if not anchors:
            return ()
        if walkable_area.is_empty:
            raise PhysicalRouteUnreachableError(
                f"walking domain for level {level_id!r} is empty"
            )

        engine = self._routing_engine(walkable_area, level_id)
        current = self._safe_endpoint(walkable_area, start, 0.0, "start")
        waypoints: list[Point] = []
        for anchor in anchors:
            target = self._safe_endpoint(walkable_area, anchor, clearance, "target")
            if hypot(current[0] - target[0], current[1] - target[1]) <= 0.001:
                current = target
                continue
            try:
                segment = tuple(
                    (float(point[0]), float(point[1]))
                    for point in engine.compute_waypoints(current, target)
                )
            except Exception as exc:
                raise PhysicalRouteUnreachableError(
                    f"no walkable route on level {level_id!r} from {current!r} to {target!r}"
                ) from exc
            self._validate_segment(walkable_area, segment, level_id)
            self._append_deduped(waypoints, segment[1:] if segment else (target,))
            current = target
        return tuple(waypoints)

    def _routing_engine(self, walkable_area: Any, level_id: str | None):
        key = (level_id, bytes(walkable_area.wkb))
        cached = self._engines.get(key)
        if cached is not None:
            return cached
        try:
            import jupedsim as jps

            engine = jps.RoutingEngine(walkable_area)
        except Exception as exc:
            raise PhysicalRouteUnreachableError(
                f"cannot build a connected walking domain for level {level_id!r}"
            ) from exc
        self._engines[key] = engine
        return engine

    @staticmethod
    def _safe_endpoint(
        walkable_area: Any,
        point: Point,
        clearance: float,
        label: str,
    ) -> Point:
        if not walkable_area.buffer(1e-7).covers(ShapelyPoint(point)):
            raise PhysicalRouteUnreachableError(
                f"physical route {label} {point!r} is outside the walkable area"
            )
        return project_to_safe_point(
            walkable_area,
            point,
            clearance=max(0.0, float(clearance)),
            require_inside=True,
        )

    @staticmethod
    def _validate_segment(
        walkable_area: Any,
        segment: tuple[Point, ...],
        level_id: str | None,
    ) -> None:
        if not segment:
            raise PhysicalRouteUnreachableError(
                f"navigation mesh returned no route on level {level_id!r}"
            )
        if len(segment) == 1:
            if walkable_area.buffer(1e-7).covers(ShapelyPoint(segment[0])):
                return
        elif walkable_area.buffer(1e-7).covers(LineString(segment)):
            return
        raise PhysicalRouteUnreachableError(
            f"navigation mesh route leaves the walkable area on level {level_id!r}"
        )

    @staticmethod
    def _append_deduped(destination: list[Point], points: tuple[Point, ...]) -> None:
        for point in points:
            if destination and hypot(
                destination[-1][0] - point[0], destination[-1][1] - point[1]
            ) <= 0.001:
                continue
            destination.append(point)
