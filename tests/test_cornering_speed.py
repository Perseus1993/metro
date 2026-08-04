from __future__ import annotations

from math import pi
from types import SimpleNamespace

import pytest

from metro_station.adapters.simulation.movement.cornering_speed import (
    corner_speed_limit_mps,
    desired_cornering_speed_mps,
    transition_speed_limit_mps,
    turn_angle_radians,
)


def _scenario():
    return SimpleNamespace(
        cornering_acceleration_limit_m_s2=3.2,
        cornering_acceleration_window_s=0.4,
        movement_trace_sample_seconds=0.2,
        cornering_lookahead_m=2.5,
        cornering_recovery_m=1.2,
        cornering_min_speed_mps=0.35,
        cornering_unknown_transition_speed_mps=0.65,
        cornering_min_turn_degrees=30.0,
    )


def test_turn_angle_and_speed_limit_follow_vector_acceleration_budget() -> None:
    scenario = _scenario()
    angle = turn_angle_radians((0.0, 0.0), (2.0, 0.0), (2.0, 2.0))

    assert angle == pytest.approx(pi / 2.0)
    assert corner_speed_limit_mps(1.4, angle, scenario) == pytest.approx(
        3.2 * 0.2 / (2.0**0.5)
    )


def test_corner_controller_slows_on_approach_and_recovers_by_distance() -> None:
    scenario = _scenario()
    passenger = SimpleNamespace(
        pos=(1.9, 0.0),
        target=(2.0, 0.0),
        route=[(2.0, 2.0)],
        route_segment_start=(0.0, 0.0),
        corner_recovery_anchor=None,
        corner_recovery_speed_limit_mps=None,
        model=SimpleNamespace(scenario=scenario),
    )

    approach = desired_cornering_speed_mps(passenger, 1.4)
    assert 0.35 < approach < 1.0

    passenger.route = []
    passenger.pos = (2.0, 0.3)
    passenger.target = (2.0, 2.0)
    passenger.corner_recovery_anchor = (2.0, 0.0)
    passenger.corner_recovery_speed_limit_mps = approach
    recovering = desired_cornering_speed_mps(passenger, 1.4)
    assert approach < recovering < 1.4

    passenger.pos = (2.0, 1.3)
    assert desired_cornering_speed_mps(passenger, 1.4) < 1.4
    assert passenger.corner_recovery_anchor is None


def test_unresolved_tactical_target_is_approached_slowly() -> None:
    scenario = _scenario()
    passenger = SimpleNamespace(
        pos=(1.9, 0.0),
        target=(2.0, 0.0),
        route=[],
        route_segment_start=(0.0, 0.0),
        corner_recovery_anchor=None,
        corner_recovery_speed_limit_mps=None,
        model=SimpleNamespace(scenario=scenario),
    )

    assert desired_cornering_speed_mps(passenger, 1.4) < 0.7


def test_cross_command_transition_obeys_vector_acceleration_budget() -> None:
    scenario = _scenario()
    limit = transition_speed_limit_mps(
        (1.1, 0.0),
        (-1.0, 0.0),
        1.4,
        scenario,
        acceleration_window_s=0.4,
    )

    assert limit == pytest.approx(3.2 * 0.4 - 1.1)
    assert abs(-limit - 1.1) <= 3.2 * 0.4 + 1e-9


@pytest.mark.parametrize("direction", [(0.0, 1.0), (-1.0, 0.0)])
def test_cross_command_transition_reports_infeasible_vector(direction) -> None:
    assert (
        transition_speed_limit_mps(
            (1.4, 0.0),
            direction,
            1.4,
            _scenario(),
        )
        is None
    )
