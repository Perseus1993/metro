from __future__ import annotations

from .constants import RIGHT_ENTRY_CORRIDOR_RADIUS_M, WAYPOINT_RADIUS_M


def entry_start_for_side(side: str, lane: int = 1) -> tuple[float, float]:
    if side == "left":
        return (
            0.128 + lane * 0.020,
            0.182 + lane * 0.020,
        )
    return (
        0.910 - lane * 0.020,
        0.192 + lane * 0.024,
    )


def entry_gate_decision_path(side: str, lane: int = 1) -> list[tuple[float, float]]:
    if side == "left":
        y_shift = (lane - 1) * 0.012
        return [
            (0.158 + lane * 0.010, 0.205 + y_shift),
            (0.185 + lane * 0.012, 0.232 + y_shift),
            (0.230 + lane * 0.018, 0.268 + y_shift),
        ]
    y_shift = (lane - 1) * 0.014
    lane_shift = (lane - 1) * 0.010
    # Right entrants use corridor-sized targets instead of a narrow string of
    # one-meter points, so groups can fan through the unpaid concourse.
    return [
        (0.850 - lane * 0.012, 0.246 + y_shift),
        (0.842 - lane_shift * 0.4, 0.262 + y_shift * 0.30),
        (0.824 - lane_shift * 0.3, 0.278 + y_shift * 0.18),
    ]


def entry_gate_approach_radius(side: str) -> float:
    return RIGHT_ENTRY_CORRIDOR_RADIUS_M if side == "right" else WAYPOINT_RADIUS_M
