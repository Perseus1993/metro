from __future__ import annotations

from collections.abc import Callable
from math import hypot
from typing import Any

from .geometry import project_to_safe_point


Point = tuple[float, float]
ALIGHTING_SOURCE_LANE_COUNT = 4
ALIGHTING_SOURCE_SEARCH_WINDOW = 64
ALIGHTING_SOURCE_FIRST_ROW_OFFSET_M = 0.35


def alighting_source_spacing_m(agent_radius_m: float) -> float:
    return max(0.4, float(agent_radius_m) * 2.2)


def alighting_source_projection_clearance_m(agent_radius_m: float) -> float:
    return max(0.02, float(agent_radius_m) * 1.05)


def alighting_source_raw_candidate(
    base: Point,
    queue_anchor: Point,
    candidate_index: int,
    *,
    agent_radius_m: float,
) -> Point:
    """Return one door-local source-lattice point used by runtime admission."""

    inward_x = float(queue_anchor[0]) - float(base[0])
    inward_y = float(queue_anchor[1]) - float(base[1])
    length = hypot(inward_x, inward_y)
    if length <= 0.001:
        inward_x, inward_y = 0.0, -1.0
    else:
        inward_x /= length
        inward_y /= length
    side_x, side_y = -inward_y, inward_x
    spacing = alighting_source_spacing_m(agent_radius_m)
    lane = int(candidate_index) % ALIGHTING_SOURCE_LANE_COUNT
    row = int(candidate_index) // ALIGHTING_SOURCE_LANE_COUNT
    side_offset = (lane - 1.5) * spacing
    inward_offset = ALIGHTING_SOURCE_FIRST_ROW_OFFSET_M + row * spacing
    return (
        float(base[0]) + inward_x * inward_offset + side_x * side_offset,
        float(base[1]) + inward_y * inward_offset + side_y * side_offset,
    )


def materialize_alighting_source_candidates(
    base: Point,
    queue_anchor: Point,
    walkable: Any,
    *,
    agent_radius_m: float,
    peak_batch: int,
    clamp: Callable[[Point], Point] | None = None,
) -> tuple[Point, ...]:
    """Materialize every source cell runtime may inspect for one peak batch.

    Runtime body ``i`` searches ``[i, i + 64)``.  The union for a batch of B
    bodies is therefore ``64 + B - 1`` cells.  Projecting the full union at
    compile time turns source placement from an implicit runtime convention
    into a finite, auditable spatial resource.
    """

    batch = max(1, int(peak_batch))
    candidate_count = ALIGHTING_SOURCE_SEARCH_WINDOW + batch - 1
    projection_clearance = alighting_source_projection_clearance_m(agent_radius_m)
    points: list[Point] = []
    for index in range(candidate_count):
        raw = alighting_source_raw_candidate(
            base,
            queue_anchor,
            index,
            agent_radius_m=agent_radius_m,
        )
        projected_input = raw if clamp is None else clamp(raw)
        try:
            point = project_to_safe_point(
                walkable,
                projected_input,
                clearance=projection_clearance,
                require_inside=False,
            )
        except Exception:
            continue
        points.append((float(point[0]), float(point[1])))
    return tuple(points)


__all__ = [
    "ALIGHTING_SOURCE_SEARCH_WINDOW",
    "alighting_source_projection_clearance_m",
    "alighting_source_raw_candidate",
    "alighting_source_spacing_m",
    "materialize_alighting_source_candidates",
]
