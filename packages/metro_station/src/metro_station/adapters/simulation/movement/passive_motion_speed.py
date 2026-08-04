from __future__ import annotations


def bounded_passive_speed_mps(
    *,
    distance_m: float,
    requested_speed_mps: float,
    current_speed_mps: float,
    control_interval_s: float,
    observation_interval_s: float,
    acceleration_limit_m_s2: float,
    minimum_speed_mps: float = 0.001,
) -> float:
    """Return a trace-resolvable speed for a process-owned native motion.

    JuPedSim receives one passive target per Mesa control interval, while the
    scientific trajectory is observed more frequently.  Limiting velocity by
    the coarse control interval permits a 0 -> walking-speed jump in one trace
    sample.  This bound uses the observation interval and reserves enough
    distance before an endpoint for one final, acceleration-bounded braking
    sample.  It applies equally to queue compaction, same-floor facilities,
    platform layout motion, and train-door crossings.
    """

    distance = max(0.0, float(distance_m))
    requested = max(0.0, float(requested_speed_mps))
    current = max(0.0, float(current_speed_mps))
    control_dt = max(1e-9, float(control_interval_s))
    observation_dt = max(1e-9, min(control_dt, float(observation_interval_s)))
    acceleration = max(1e-9, float(acceleration_limit_m_s2))
    minimum = max(1e-9, float(minimum_speed_mps))

    resolvable_delta = acceleration * observation_dt
    lower = max(minimum, current - resolvable_delta)
    upper = min(requested, current + resolvable_delta)

    # If the endpoint is farther than one bounded braking interval, preserve
    # the distance needed for the next command to decelerate.  Otherwise use
    # the remaining control interval, with ``lower`` retaining continuity
    # when the body is already inside the last observation-length segment.
    if distance <= resolvable_delta * control_dt:
        endpoint_cap = distance / control_dt
    else:
        endpoint_cap = (
            distance + resolvable_delta * observation_dt
        ) / (control_dt + observation_dt)
    return max(lower, min(max(minimum, upper), max(minimum, endpoint_cap)))


__all__ = ["bounded_passive_speed_mps"]
