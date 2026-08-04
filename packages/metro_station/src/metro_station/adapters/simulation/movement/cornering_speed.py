from __future__ import annotations

from math import acos, hypot, sin, sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


Point = tuple[float, float]


def desired_cornering_speed_mps(
    passenger: PassengerAgent,
    base_speed_mps: float,
) -> float:
    """Bound desired speed around tactical polyline corners.

    JuPedSim's collision-free-speed model avoids bodies and walls but does not
    impose pedestrian turning kinematics when a waypoint journey is switched.
    This controller anticipates the next route segment and carries the same
    speed limit a short distance out of the corner.
    """

    base = max(0.001, float(base_speed_mps))
    scenario = passenger.model.scenario
    speed = base
    if passenger.route:
        angle = turn_angle_radians(
            passenger.route_segment_start,
            passenger.target,
            passenger.route[0],
        )
        limit = corner_speed_limit_mps(base, angle, scenario)
        if limit < base:
            distance = hypot(
                passenger.target[0] - passenger.pos[0],
                passenger.target[1] - passenger.pos[1],
            )
            speed = min(
                speed,
                _blended_speed(
                    limit,
                    base,
                    distance / float(scenario.cornering_lookahead_m),
                ),
            )
    else:
        # The next tactical route is not known until the current goal region
        # is entered.  Treat that boundary as an unresolved decision corner
        # and arrive slowly enough for any subsequent legal direction.
        distance = hypot(
            passenger.target[0] - passenger.pos[0],
            passenger.target[1] - passenger.pos[1],
        )
        speed = min(
            speed,
            _blended_speed(
                min(base, float(scenario.cornering_unknown_transition_speed_mps)),
                base,
                distance / float(scenario.cornering_lookahead_m),
            ),
        )

    if passenger.corner_recovery_anchor is not None:
        distance = hypot(
            passenger.pos[0] - passenger.corner_recovery_anchor[0],
            passenger.pos[1] - passenger.corner_recovery_anchor[1],
        )
        if distance >= float(scenario.cornering_recovery_m):
            passenger.corner_recovery_anchor = None
            passenger.corner_recovery_speed_limit_mps = None
        else:
            limit = min(
                base,
                float(passenger.corner_recovery_speed_limit_mps or base),
            )
            speed = min(
                speed,
                _blended_speed(
                    limit,
                    base,
                    distance / float(scenario.cornering_recovery_m),
                ),
            )
    return max(0.001, min(base, speed))


def corner_speed_limit_mps(base_speed_mps: float, angle_radians: float, scenario) -> float:
    minimum_angle = float(scenario.cornering_min_turn_degrees) * 3.141592653589793 / 180.0
    if angle_radians < minimum_angle:
        return float(base_speed_mps)
    direction_change = 2.0 * sin(angle_radians * 0.5)
    if direction_change <= 1e-9:
        return float(base_speed_mps)
    acceleration_budget = (
        float(scenario.cornering_acceleration_limit_m_s2)
        * _resolved_acceleration_window_s(scenario)
    )
    kinematic_limit = acceleration_budget / direction_change
    return max(
        float(scenario.cornering_min_speed_mps),
        min(float(base_speed_mps), kinematic_limit),
    )


def transition_speed_limit_mps(
    previous_velocity_mps: Point,
    next_direction: Point,
    upper_speed_mps: float,
    scenario,
    *,
    acceleration_window_s: float | None = None,
) -> float | None:
    """Return the fastest new-direction velocity inside the vector budget.

    A tactical command can replace a route before its next direction was known,
    so limiting both sides of a precomputed polyline corner is impossible. In
    that case solve ``|speed * direction - previous_velocity| <= a * window``
    from the last committed physical velocity.
    """

    direction_length = hypot(next_direction[0], next_direction[1])
    previous_speed = hypot(previous_velocity_mps[0], previous_velocity_mps[1])
    upper = max(0.001, float(upper_speed_mps))
    if direction_length <= 1e-9 or previous_speed <= 1e-9:
        return upper
    unit = (
        next_direction[0] / direction_length,
        next_direction[1] / direction_length,
    )
    parallel = (
        previous_velocity_mps[0] * unit[0]
        + previous_velocity_mps[1] * unit[1]
    )
    perpendicular_squared = max(0.0, previous_speed**2 - parallel**2)
    budget = (
        float(scenario.cornering_acceleration_limit_m_s2)
        * _resolved_acceleration_window_s(
            scenario,
            override=acceleration_window_s,
        )
    )
    remaining_squared = budget**2 - perpendicular_squared
    if remaining_squared <= 0.0:
        return None
    feasible_upper = parallel + sqrt(remaining_squared)
    if feasible_upper <= 0.0:
        return None
    return max(0.001, min(upper, feasible_upper))


def turn_angle_radians(start: Point, corner: Point, end: Point) -> float:
    incoming = (corner[0] - start[0], corner[1] - start[1])
    outgoing = (end[0] - corner[0], end[1] - corner[1])
    incoming_length = hypot(incoming[0], incoming[1])
    outgoing_length = hypot(outgoing[0], outgoing[1])
    if incoming_length <= 1e-9 or outgoing_length <= 1e-9:
        return 0.0
    cosine = (
        incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    ) / (incoming_length * outgoing_length)
    return acos(max(-1.0, min(1.0, cosine)))


def _blended_speed(lower: float, upper: float, progress: float) -> float:
    ratio = max(0.0, min(1.0, float(progress)))
    return lower + (upper - lower) * ratio


def _resolved_acceleration_window_s(
    scenario,
    *,
    override: float | None = None,
) -> float:
    if override is not None:
        return max(1e-9, float(override))
    scientific_window = float(scenario.cornering_acceleration_window_s)
    observation_window = float(
        getattr(scenario, "movement_trace_sample_seconds", scientific_window)
    )
    return max(1e-9, min(scientific_window, observation_window))


__all__ = [
    "corner_speed_limit_mps",
    "desired_cornering_speed_mps",
    "transition_speed_limit_mps",
    "turn_angle_radians",
]
