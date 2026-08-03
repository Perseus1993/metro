from __future__ import annotations

from math import hypot, sqrt
from typing import Iterable

from ..planning.plan import WALKING_STATES


Point = tuple[float, float]


def minimum_body_clearance(model) -> float:
    scenario = model.scenario
    return max(
        0.05,
        float(getattr(scenario, "jupedsim_agent_radius_units", 0.18))
        * float(getattr(scenario, "jupedsim_clearance_multiplier", 2.2)),
    )


def external_body_positions(
    model,
    *,
    level_id: str | None,
    excluded_passenger_ids: Iterable[int] = (),
    passive_only: bool = False,
) -> tuple[Point, ...]:
    excluded = {int(value) for value in excluded_passenger_ids}
    result: list[Point] = []
    for passenger in tuple(getattr(model, "passengers", ())):
        passenger_id = int(passenger.unique_id)
        if passenger_id in excluded or passenger.current_level_id != level_id:
            continue
        if passive_only and (
            passenger.state in WALKING_STATES
            and not bool(passenger.passive_facility_service)
        ):
            continue
        result.append(tuple(passenger.pos))
    return tuple(result)


def constrain_motion_segment(
    start: Point,
    proposed: Point,
    occupied_positions: Iterable[Point],
    *,
    minimum_distance: float,
    maximum_displacement: float | None = None,
) -> tuple[Point, bool]:
    """Clip a motion proposal at the first body-clear contact boundary."""

    dx = proposed[0] - start[0]
    dy = proposed[1] - start[1]
    distance = hypot(dx, dy)
    if maximum_displacement is not None and distance > maximum_displacement + 1e-12:
        ratio = max(0.0, float(maximum_displacement)) / distance
        dx *= ratio
        dy *= ratio
        proposed = start[0] + dx, start[1] + dy
        distance = max(0.0, float(maximum_displacement))
    if distance <= 1e-12:
        return start, False

    earliest_contact = 1.0
    blocked = False
    radius = max(0.0, float(minimum_distance))
    radius_squared = radius * radius
    length_squared = dx * dx + dy * dy
    for occupied in occupied_positions:
        offset_x = start[0] - occupied[0]
        offset_y = start[1] - occupied[1]
        start_distance = hypot(offset_x, offset_y)
        if start_distance < radius - 1e-9:
            return start, True
        linear = 2.0 * (offset_x * dx + offset_y * dy)
        constant = offset_x * offset_x + offset_y * offset_y - radius_squared
        discriminant = linear * linear - 4.0 * length_squared * constant
        if discriminant < 0.0:
            continue
        root = sqrt(max(0.0, discriminant))
        entry = (-linear - root) / (2.0 * length_squared)
        exit_ = (-linear + root) / (2.0 * length_squared)
        if exit_ < 0.0 or entry > 1.0:
            continue
        contact = max(0.0, entry)
        if contact <= earliest_contact:
            earliest_contact = contact
            blocked = True

    if not blocked:
        return proposed, False
    safe_ratio = max(0.0, earliest_contact - 1e-7 / max(distance, 1e-9))
    return (start[0] + dx * safe_ratio, start[1] + dy * safe_ratio), True
