from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from shapely.geometry import LineString, Point as ShapelyPoint
from shapely.ops import nearest_points

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
        self._navigation_contexts: dict[
            tuple[str | None, bytes, float], tuple[Any, Any, Any]
        ] = {}

    def clear(self) -> None:
        self._engines.clear()
        self._navigation_contexts.clear()

    def route(
        self,
        walkable_area: Any,
        start: Point,
        anchors: tuple[Point, ...],
        *,
        level_id: str | None,
        clearance: float,
        include_navigation_waypoints: bool = True,
    ) -> tuple[Point, ...]:
        if not anchors:
            return ()
        if walkable_area.is_empty:
            raise PhysicalRouteUnreachableError(
                f"walking domain for level {level_id!r} is empty"
            )

        navigation_domain, routing_domain, engine = self._navigation_context(
            walkable_area,
            level_id,
            clearance,
        )
        current = self._safe_endpoint(
            walkable_area,
            navigation_domain,
            start,
            "agent-clear start",
        )
        waypoints: list[Point] = []
        for anchor in anchors:
            target = self._safe_endpoint(
                walkable_area,
                navigation_domain,
                anchor,
                "target",
            )
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
            self._validate_segment(routing_domain, segment, level_id)
            # JuPedSim performs its own navigation-mesh wayfinding towards a
            # stage. Runtime movement commands therefore need semantic
            # anchors only; replaying every RoutingEngine corner as a separate
            # stage creates corner-local minima and lets stage tolerances cut
            # across obstacles. The full polyline remains available for
            # geodesic walking-cost queries and compiler evidence.
            command_points = (
                segment[1:]
                if include_navigation_waypoints and segment
                else (target,)
            )
            self._append_deduped(waypoints, command_points)
            current = target
        return tuple(waypoints)

    def _navigation_context(
        self,
        walkable_area: Any,
        level_id: str | None,
        clearance: float,
    ) -> tuple[Any, Any, Any]:
        normalized_clearance = max(0.0, float(clearance))
        key = (
            level_id,
            bytes(walkable_area.wkb),
            round(normalized_clearance, 9),
        )
        cached = self._navigation_contexts.get(key)
        if cached is not None:
            return cached
        navigation_domain = walkable_area.buffer(
            -normalized_clearance,
            join_style="mitre",
        )
        if navigation_domain.is_empty or navigation_domain.geom_type not in {
            "Polygon",
            "MultiPolygon",
        }:
            raise PhysicalRouteUnreachableError(
                f"walking domain for level {level_id!r} has no agent-clear navigation core"
            )
        # Match the compiler's radius-shrunk domain while adding only a
        # micrometre numerical skin for JuPedSim's point classifier.
        routing_domain = navigation_domain.buffer(1e-6)
        engine = self._routing_engine(routing_domain, level_id)
        result = navigation_domain, routing_domain, engine
        self._navigation_contexts[key] = result
        return result

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
        navigation_domain: Any,
        point: Point,
        label: str,
    ) -> Point:
        source = ShapelyPoint(point)
        if not walkable_area.covers(source) and not walkable_area.buffer(1e-7).covers(
            source
        ):
            raise PhysicalRouteUnreachableError(
                f"physical route {label} {point!r} is outside the walkable area"
            )
        if navigation_domain.covers(source):
            return point
        _source, projected = nearest_points(source, navigation_domain)
        return float(projected.x), float(projected.y)

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
            geometry = ShapelyPoint(segment[0])
            if walkable_area.covers(geometry) or walkable_area.buffer(1e-7).covers(
                geometry
            ):
                return
        else:
            geometry = LineString(segment)
            if walkable_area.covers(geometry) or walkable_area.buffer(1e-7).covers(
                geometry
            ):
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
