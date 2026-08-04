from __future__ import annotations

from math import cos, radians, sin

from metro_station_acceptance.blind_trajectory_gate import analyze_blind_trajectory


def _straight(agent_id: str, *, y: float = 0.0) -> list[dict[str, object]]:
    return [
        {"id": agent_id, "t": index * 0.2, "x": index * 0.2, "y": y}
        for index in range(21)
    ]


def test_blind_gate_accepts_realistic_anonymous_motion() -> None:
    report = analyze_blind_trajectory(_straight("anonymous-1"))

    assert report["passed"]
    assert report["metrics"]["speed_p99_m_s"] == 1.0
    assert report["metrics"]["acceleration_p99_m_s2"] == 0.0


def test_blind_gate_rejects_shared_paths_without_station_knowledge() -> None:
    observations = [*_straight("anonymous-1"), *_straight("anonymous-2")]

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert not report["checks"]["different_ids_never_share_exact_position"]
    assert report["metrics"]["instantaneous_exact_colocation_count"] > 0


def test_blind_gate_rejects_sustained_unrealistic_acceleration() -> None:
    observations = [
        {"id": "anonymous-1", "t": index * 0.2, "x": x, "y": 0.0}
        for index, x in enumerate((0.0, 0.0, 0.0, 0.4, 0.8, 1.2, 1.6))
    ]

    report = analyze_blind_trajectory(observations)

    assert not report["checks"]["acceleration_p99_within_limit"]
    assert report["metrics"]["acceleration_window_s"] == 0.4


def test_blind_gate_does_not_invent_acceleration_across_cadence_gap() -> None:
    observations = [
        {"id": "anonymous-1", "t": t, "x": x, "y": 0.0}
        for t, x in (
            (0.0, 0.0),
            (0.2, 0.2),
            (0.4, 0.4),
            (0.6, 0.6),
            (1.2, 0.6),
            (1.4, 0.6),
            (1.6, 0.6),
            (1.8, 0.6),
        )
    ]

    report = analyze_blind_trajectory(observations)

    assert report["checks"]["acceleration_p99_within_limit"]


def test_blind_gate_counts_displaced_cadence_gap_as_motion() -> None:
    observations = [
        {"id": "anonymous-1", "t": index * 0.2, "x": index * 0.2, "y": 0.0}
        for index in range(5)
    ]
    observations.extend(
        {"id": "anonymous-1", "t": 1.4 + index * 0.2, "x": 100.0 + index * 0.2, "y": 0.0}
        for index in range(5)
    )

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert not report["checks"]["speed_p99_within_limit"]
    assert report["metrics"]["speed_max_m_s"] > 100.0
    assert report["metrics"]["sampling_gap_with_displacement_count"] == 1


def test_blind_gate_rejects_one_full_speed_151_degree_turn() -> None:
    dt = 0.2
    direction = radians(151.0)
    observations = []
    x = 0.0
    y = 0.0
    for sample_index in range(302):
        observations.append(
            {"id": "anonymous-1", "t": sample_index * dt, "x": x, "y": y}
        )
        if sample_index < 151:
            x += dt
        else:
            x += cos(direction) * dt
            y += sin(direction) * dt

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["large_moving_turn_count"] == 1
    assert report["metrics"]["large_moving_turn_fraction"] < 0.005
    assert not report["checks"]["large_turn_absolute_count_within_limit"]


def test_blind_gate_treats_one_slow_large_turn_as_diagnostic_not_hard_failure() -> None:
    dt = 0.2
    speed = 0.3
    direction = radians(151.0)
    observations = []
    x = 0.0
    y = 0.0
    for sample_index in range(302):
        observations.append(
            {"id": "anonymous-1", "t": sample_index * dt, "x": x, "y": y}
        )
        if sample_index < 151:
            x += speed * dt
        else:
            x += cos(direction) * speed * dt
            y += sin(direction) * speed * dt

    report = analyze_blind_trajectory(observations)

    assert report["passed"]
    assert report["checks"]["large_turn_fraction_within_limit"]
    assert not report["checks"]["large_turn_absolute_count_within_limit"]
    assert (
        "large_turn_absolute_count_within_limit"
        in report["diagnostic_check_names"]
    )


def test_blind_gate_preserves_same_time_dual_position_failure() -> None:
    observations = [
        {"id": "anonymous-1", "t": 0.0, "x": 0.0, "y": 0.0},
        {"id": "anonymous-1", "t": 0.0, "x": 99.0, "y": 0.0},
        *_straight("anonymous-1")[1:],
    ]

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["same_id_dual_position_count"] == 1
    assert not report["checks"]["same_id_never_has_two_positions_at_once"]
    assert report["examples"]["same_id_dual_positions"] == [
        {
            "agent_id": "anonymous-1",
            "time_s": 0.0,
            "positions": [
                {"x": 0.0, "y": 0.0},
                {"x": 99.0, "y": 0.0},
            ],
        }
    ]


def test_blind_gate_uses_worst_agent_p99_not_only_population_p99() -> None:
    normal = [
        {"id": "normal", "t": index * 0.2, "x": index * 0.2, "y": 0.0}
        for index in range(1001)
    ]
    fast = [
        {"id": "fast", "t": index * 0.2, "x": index * 0.42, "y": 10.0}
        for index in range(11)
    ]

    report = analyze_blind_trajectory([*normal, *fast])

    assert report["metrics"]["speed_p99_m_s"] <= 2.0
    assert report["metrics"]["maximum_agent_speed_p99_m_s"] > 2.0
    assert not report["checks"]["each_agent_speed_p99_within_limit"]


def test_blind_gate_rejects_periodic_walk_stop_aliasing() -> None:
    observations = []
    x = 0.0
    for sample_index in range(302):
        observations.append(
            {"id": "anonymous-1", "t": sample_index * 0.2, "x": x, "y": 0.0}
        )
        x += 0.2 if sample_index % 2 == 0 else 0.0

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["isolated_stop_sample_count"] > 100
    assert report["metrics"]["adjacent_acceleration_p99_m_s2"] >= 5.0 - 1e-9
    assert not report["checks"]["adjacent_acceleration_p99_within_limit"]
    assert not report["checks"]["isolated_stop_fraction_within_limit"]


def test_blind_gate_applies_quantization_margin_only_to_adjacent_estimator() -> None:
    observations = []
    position = 0.0
    speeds = (0.5, 0.5, 0.5, 1.4, 1.4, 1.4)
    observations.append({"id": "anonymous-1", "t": 0.0, "x": position, "y": 0.0})
    for sample_index, speed in enumerate(speeds, start=1):
        position += speed * 0.2
        observations.append(
            {
                "id": "anonymous-1",
                "t": sample_index * 0.2,
                "x": position,
                "y": 0.0,
            }
        )

    report = analyze_blind_trajectory(observations)

    assert report["metrics"]["acceleration_p99_m_s2"] <= 4.0
    assert 4.0 < report["metrics"]["adjacent_acceleration_p99_m_s2"] <= 4.5
    assert report["checks"]["acceleration_p99_within_limit"]
    assert report["checks"]["adjacent_acceleration_p99_within_limit"]
    assert report["passed"]


def test_blind_gate_rejects_periodic_120_degree_zigzag_aliasing() -> None:
    direction = radians(120.0)
    observations = []
    x = 0.0
    y = 0.0
    for sample_index in range(302):
        observations.append(
            {"id": "anonymous-1", "t": sample_index * 0.2, "x": x, "y": y}
        )
        angle = 0.0 if sample_index % 2 == 0 else direction
        x += cos(angle) * 0.2
        y += sin(angle) * 0.2

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["large_moving_turn_count"] == 0
    assert report["metrics"]["adjacent_acceleration_p99_m_s2"] > 8.0
    assert not report["checks"]["adjacent_acceleration_p99_within_limit"]


def test_blind_gate_rejects_one_diluted_segment_speed_spike() -> None:
    observations = []
    x = 0.0
    for sample_index in range(1002):
        observations.append(
            {"id": "anonymous-1", "t": sample_index * 0.2, "x": x, "y": 0.0}
        )
        x += 1.0 if sample_index == 500 else 0.2

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["speed_p99_m_s"] <= 2.0
    assert report["metrics"]["speed_max_m_s"] >= 5.0 - 1e-9
    assert not report["checks"]["no_segment_exceeds_physical_speed_limit"]


def test_blind_gate_uses_pair_common_samples_after_cadence_change() -> None:
    observations = []
    for sample_index in range(4):
        time_s = sample_index * 0.2
        observations.extend(
            (
                {"id": "a", "t": time_s, "x": 0.0, "y": 0.0},
                {"id": "b", "t": time_s, "x": 1.0, "y": 0.0},
            )
        )
    for time_s in (2.0, 3.0, 4.0):
        observations.extend(
            (
                {"id": "a", "t": time_s, "x": 0.0, "y": 0.0},
                {"id": "b", "t": time_s, "x": 0.01, "y": 0.0},
            )
        )

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["persistent_near_colocation_count"] == 1


def test_blind_gate_rejects_sustained_three_centimeter_center_overlap() -> None:
    observations = [
        record
        for sample_index in range(26)
        for record in (
            {"id": "a", "t": sample_index * 0.2, "x": 0.0, "y": 0.0},
            {"id": "b", "t": sample_index * 0.2, "x": 0.03, "y": 0.0},
        )
    ]

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["persistent_near_colocation_count"] == 1


def test_blind_gate_does_not_treat_different_levels_as_body_overlap() -> None:
    observations = [
        record
        for sample_index in range(26)
        for record in (
            {
                "id": "a",
                "t": sample_index * 0.2,
                "x": 10.0,
                "y": 20.0,
                "level": "l0001",
            },
            {
                "id": "b",
                "t": sample_index * 0.2,
                "x": 10.0,
                "y": 20.0,
                "level": "l0002",
            },
        )
    ]

    report = analyze_blind_trajectory(observations)

    assert report["checks"]["different_ids_never_share_exact_position"]
    assert report["checks"]["no_persistent_near_colocation"]
    assert report["checks"]["no_interpolated_body_overlap"]


def test_blind_gate_rejects_between_sample_head_on_crossing() -> None:
    observations = [
        record
        for sample_index in range(302)
        for record in (
            {
                "id": "a",
                "t": sample_index * 0.2,
                "x": -0.9 + sample_index * 0.2,
                "y": 0.0,
            },
            {
                "id": "b",
                "t": sample_index * 0.2,
                "x": 0.9 - sample_index * 0.2,
                "y": 0.0,
            },
        )
    ]

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["interpolated_body_overlap_pair_count"] == 1
    assert not report["checks"]["no_interpolated_body_overlap"]


def test_blind_gate_rejects_single_full_speed_105_degree_kink() -> None:
    direction = radians(105.0)
    observations = []
    x = 0.0
    y = 0.0
    for sample_index in range(302):
        observations.append(
            {"id": "a", "t": sample_index * 0.2, "x": x, "y": y}
        )
        angle = direction if sample_index == 151 else 0.0
        x += cos(angle) * 0.2
        y += sin(angle) * 0.2

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["high_speed_turn_count"] == 2
    assert not report["checks"]["high_speed_turn_absolute_count_within_limit"]


def test_blind_gate_rejects_sustained_nineteen_centimeter_center_overlap() -> None:
    observations = [
        record
        for sample_index in range(302)
        for record in (
            {"id": "a", "t": sample_index * 0.2, "x": 0.0, "y": 0.0},
            {"id": "b", "t": sample_index * 0.2, "x": 0.19, "y": 0.0},
        )
    ]

    report = analyze_blind_trajectory(observations)

    assert not report["passed"]
    assert report["metrics"]["persistent_near_colocation_count"] == 1
