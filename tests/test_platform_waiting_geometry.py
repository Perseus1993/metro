from __future__ import annotations

from types import SimpleNamespace

from metro_station.adapters.simulation.runtime.platform_waiting_geometry import (
    platform_waiting_slot_sort_key,
)


def test_stall_recovery_prefers_the_nearest_platform_slot() -> None:
    passenger = SimpleNamespace(
        intent="enter_and_board",
        pos=(4.0, 2.0),
        _platform_waiting_stall_recovery=True,
    )

    near = platform_waiting_slot_sort_key(
        (5.0, 2.0),
        passenger=passenger,
        exit_staging_anchors=(),
        boarding_staging_anchors=((100.0, 100.0),),
        queue_access_axes=(),
        fallback_anchors=(),
    )
    far = platform_waiting_slot_sort_key(
        (8.0, 2.0),
        passenger=passenger,
        exit_staging_anchors=(),
        boarding_staging_anchors=((100.0, 100.0),),
        queue_access_axes=(),
        fallback_anchors=(),
    )

    assert near < far
    assert near[0] == -1.0


def test_exit_flow_prefers_exit_staging_over_boarding_staging() -> None:
    passenger = SimpleNamespace(intent="exit_station")

    key = platform_waiting_slot_sort_key(
        (2.0, 0.0),
        passenger=passenger,
        exit_staging_anchors=((0.0, 0.0),),
        boarding_staging_anchors=((2.0, 0.0),),
        queue_access_axes=(),
        fallback_anchors=(),
    )

    assert key[1] == 2.0


def test_queue_axis_keeps_upstream_slots_ahead_of_downstream_slots() -> None:
    passenger = SimpleNamespace(intent="transfer")

    upstream = platform_waiting_slot_sort_key(
        (-1.0, 0.0),
        passenger=passenger,
        exit_staging_anchors=(),
        boarding_staging_anchors=(),
        queue_access_axes=(((0.0, 0.0), (1.0, 0.0)),),
        fallback_anchors=(),
    )
    downstream = platform_waiting_slot_sort_key(
        (1.0, 0.0),
        passenger=passenger,
        exit_staging_anchors=(),
        boarding_staging_anchors=(),
        queue_access_axes=(((0.0, 0.0), (1.0, 0.0)),),
        fallback_anchors=(),
    )

    assert upstream < downstream
