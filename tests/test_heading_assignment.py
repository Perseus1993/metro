from __future__ import annotations

from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    _assign_forward_headings,
)
from metro_station_visualizer.tracks.builder import _assign_forward_track_headings


def _visual_point(time_seconds: float, heading: float) -> list[object]:
    return [
        time_seconds,
        1.0,
        2.0,
        heading,
        1.0,
        "waiting",
        "unit",
        "unit",
        False,
        {"level_id": "b1", "authority": "simulation_trace.snapshots"},
    ]


def test_segment_heading_assignment_preserves_singleton_heading() -> None:
    points = [_visual_point(0.0, 1.2)]

    _assign_forward_headings(
        points,
        snapshot_interval_seconds=1.0,
        movement_interval_seconds=0.2,
    )

    assert points[0][3] == 1.2


def test_segment_heading_assignment_holds_last_heading_while_stationary() -> None:
    points = [_visual_point(0.0, 1.2), _visual_point(1.0, -0.8)]

    _assign_forward_headings(
        points,
        snapshot_interval_seconds=1.0,
        movement_interval_seconds=0.2,
    )

    assert [point[3] for point in points] == [1.2, 1.2]


def test_legacy_heading_assignment_holds_last_heading_while_stationary() -> None:
    points = [
        [0.0, 1.0, 2.0, 1.2, 1.0],
        [1.0, 1.0, 2.0, -0.8, 1.0],
    ]
    agent: dict[str, object] = {"points": points}

    _assign_forward_track_headings([agent])

    assert [point[3] for point in points] == [1.2, 1.2]


def test_sub_centimetre_motion_does_not_flip_heading() -> None:
    points = [
        _visual_point(0.0, 1.2),
        _visual_point(0.2, -1.9),
        _visual_point(0.4, 0.3),
    ]
    points[1][1] += 0.005
    points[2][1] -= 0.004

    _assign_forward_headings(
        points,
        snapshot_interval_seconds=1.0,
        movement_interval_seconds=0.2,
    )

    assert [point[3] for point in points] == [1.2, 1.2, 1.2]
