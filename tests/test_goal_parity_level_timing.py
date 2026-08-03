from __future__ import annotations

from metro_station.adapters.simulation.runtime.goal_parity import GoalParityEvent
from metro_station.adapters.simulation.runtime.goal_parity_comparison import (
    compare_goal_event_streams,
)


def _level_event(*, stream: str, time_seconds: float, level_id: str) -> GoalParityEvent:
    return GoalParityEvent(
        passenger_id=17,
        stream=stream,
        kind="level_changed",
        time_seconds=time_seconds,
        stage="vertical_transfer",
        facility_id="vertical:test:up",
        level_id=level_id,
    )


def test_level_transition_parity_compares_time_and_authoritative_level() -> None:
    matching = compare_goal_event_streams(
        (
            _level_event(stream="physical", time_seconds=12.5, level_id="concourse"),
            _level_event(stream="graph", time_seconds=12.5, level_id="concourse"),
        ),
        [17],
    )
    wrong_time = compare_goal_event_streams(
        (
            _level_event(stream="physical", time_seconds=12.5, level_id="concourse"),
            _level_event(stream="graph", time_seconds=7.5, level_id="concourse"),
        ),
        [17],
    )
    wrong_level = compare_goal_event_streams(
        (
            _level_event(stream="physical", time_seconds=12.5, level_id="concourse"),
            _level_event(stream="graph", time_seconds=12.5, level_id="platform"),
        ),
        [17],
    )

    assert matching["level_transition_mismatches"] == []
    assert wrong_time["level_transition_mismatches"]
    assert wrong_level["level_transition_mismatches"]
