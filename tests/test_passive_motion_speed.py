from __future__ import annotations

from types import SimpleNamespace

import pytest

from metro_station.adapters.simulation.agents.passenger import PassengerAgent
from metro_station.adapters.simulation.movement.passive_motion_speed import (
    bounded_passive_speed_mps,
)


def _bounded(distance: float, current: float, requested: float = 1.2) -> float:
    return bounded_passive_speed_mps(
        distance_m=distance,
        requested_speed_mps=requested,
        current_speed_mps=current,
        control_interval_s=1.0,
        observation_interval_s=0.2,
        acceleration_limit_m_s2=3.2,
    )


def test_passive_motion_accelerates_at_the_trace_resolvable_limit() -> None:
    assert _bounded(4.0, 0.0) == pytest.approx(0.64)
    assert _bounded(3.36, 0.64) == pytest.approx(1.2)


def test_passive_motion_reserves_an_endpoint_braking_sample() -> None:
    first = _bounded(1.25, 1.2)
    remaining = 1.25 - first
    second = _bounded(remaining, first)

    assert first == pytest.approx((1.25 + 0.64 * 0.2) / 1.2)
    assert first - second <= 0.64 + 1e-9
    assert remaining >= second * 0.2 - 1e-9


def test_short_passive_motion_does_not_jump_to_cruising_speed() -> None:
    assert _bounded(0.75, 0.0) == pytest.approx(0.64)
    assert _bounded(0.11, 0.64) == pytest.approx(0.11)


def test_passive_motion_brakes_before_an_unresolvable_direction_change() -> None:
    scenario = SimpleNamespace(
        tick_seconds=1.0,
        movement_trace_sample_seconds=0.2,
        jupedsim_desired_speed_mps=1.2,
        cornering_acceleration_limit_m_s2=3.2,
        cornering_acceleration_window_s=0.4,
    )
    passenger = SimpleNamespace(
        pos=(0.0, 0.0),
        last_walk_velocity_mps=(1.0, 0.0),
        model=SimpleNamespace(scenario=scenario, step_index=7),
    )

    PassengerAgent.request_passive_layout_motion(
        passenger,
        (-2.0, 0.0),
        requested_speed_mps=1.2,
    )

    # A reversal cannot fit inside one 0.2 s observation.  Stop at the current
    # coordinate before the process requests the intended target next tick;
    # advancing and then reversing would create an A-B-A bounce.
    assert passenger.passive_layout_motion_speed_mps == pytest.approx(0.001)
    assert passenger.passive_layout_motion_target == pytest.approx((0.0, 0.0))
