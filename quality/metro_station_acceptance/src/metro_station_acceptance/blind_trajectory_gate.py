from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import acos, degrees, hypot
from typing import Any

from .trajectory_truth_colocation import (
    interpolated_near_colocations,
    instantaneous_exact_colocations,
    persistent_near_colocations,
)
from .trajectory_truth_inputs import TruthObservation, extract_truth_input


BLIND_TRAJECTORY_GATE_SCHEMA_VERSION = "blind_trajectory_gate_report.v1"


@dataclass(frozen=True)
class BlindTrajectoryGateConfig:
    max_speed_p99_m_s: float = 2.0
    max_segment_speed_m_s: float = 2.2
    max_acceleration_p99_m_s2: float = 4.0
    max_acceleration_m_s2: float = 4.0
    acceleration_window_s: float = 0.4
    # A one-cadence velocity difference is retained as an alias detector, but
    # receives a small quantization margin relative to the scientific 0.4 s
    # acceleration estimator above.  This still rejects alternating walk/stop
    # samples (5 m/s²) without failing a smooth centered estimate at 3 m/s²
    # because one adjacent pair rounded to 4.2 m/s².
    max_adjacent_acceleration_p99_m_s2: float = 4.5
    large_turn_threshold_degrees: float = 150.0
    max_large_turn_fraction: float = 0.005
    max_large_turn_count: int = 0
    high_speed_turn_threshold_degrees: float = 100.0
    high_speed_turn_min_speed_m_s: float = 0.8
    max_high_speed_turn_count: int = 0
    moving_speed_threshold_m_s: float = 0.2
    stationary_speed_threshold_m_s: float = 0.05
    max_isolated_stop_fraction: float = 0.02
    same_time_position_epsilon_m: float = 0.001
    maximum_near_colocation_distance_m: float = 0.36
    minimum_near_colocation_duration_s: float = 2.0
    minimum_near_colocation_samples: int = 3
    max_issue_examples: int = 20


@dataclass(frozen=True)
class _BlindVelocity:
    agent_id: str
    start_time_s: float
    end_time_s: float
    vx: float
    vy: float
    speed: float
    level_id: str | None

    @property
    def midpoint_time_s(self) -> float:
        return (self.start_time_s + self.end_time_s) * 0.5


def analyze_blind_trajectory(
    observations: object,
    *,
    config: BlindTrajectoryGateConfig | None = None,
) -> dict[str, Any]:
    """Judge anonymous motion without station, state, or facility knowledge."""

    active = config or BlindTrajectoryGateConfig()
    truth = extract_truth_input(observations, coordinate_unit="m")
    by_agent_time: defaultdict[
        tuple[str, float],
        set[tuple[float, float, str | None]],
    ] = defaultdict(set)
    for item in truth.observations:
        by_agent_time[(item.agent_id, item.time_s)].add(
            (item.x, item.y, item.level_id)
        )

    dual_position_examples: list[dict[str, object]] = []
    simultaneous_dual_positions = 0
    for (agent_id, time_s), positions in sorted(by_agent_time.items()):
        if not _positions_disagree(
            positions,
            epsilon_m=active.same_time_position_epsilon_m,
        ):
            continue
        simultaneous_dual_positions += 1
        if len(dual_position_examples) >= active.max_issue_examples:
            continue
        dual_position_examples.append(
            {
                "agent_id": agent_id,
                "time_s": time_s,
                "positions": [
                    {
                        "x": x,
                        "y": y,
                        **({"level_id": level_id} if level_id is not None else {}),
                    }
                    for x, y, level_id in sorted(
                        positions,
                        key=lambda value: (
                            value[2] is None,
                            value[2] or "",
                            value[0],
                            value[1],
                        ),
                    )
                ],
            }
        )
    by_agent: defaultdict[str, list[TruthObservation]] = defaultdict(list)
    unambiguous_observations: list[TruthObservation] = []
    for (agent_id, time_s), positions in sorted(by_agent_time.items()):
        if _positions_disagree(positions, epsilon_m=active.same_time_position_epsilon_m):
            continue
        x, y, level_id = sorted(
            positions,
            key=lambda value: (
                value[2] is None,
                value[0],
                value[1],
                value[2] or "",
            ),
        )[0]
        observation = TruthObservation(agent_id, time_s, x, y, 0, level_id)
        by_agent[agent_id].append(observation)
        unambiguous_observations.append(observation)
    exact_count, exact_examples = instantaneous_exact_colocations(
        unambiguous_observations,
        max_examples=active.max_issue_examples,
    )
    near_count, near_examples = persistent_near_colocations(
        unambiguous_observations,
        maximum_distance_m=active.maximum_near_colocation_distance_m,
        min_duration_s=active.minimum_near_colocation_duration_s,
        min_samples=active.minimum_near_colocation_samples,
        max_examples=active.max_issue_examples,
    )
    swept_count, swept_examples = interpolated_near_colocations(
        unambiguous_observations,
        maximum_distance_m=active.maximum_near_colocation_distance_m,
        max_examples=active.max_issue_examples,
    )

    speeds: list[float] = []
    accelerations: list[float] = []
    adjacent_accelerations: list[float] = []
    turns: list[float] = []
    high_speed_turns: list[float] = []
    speeds_by_agent: defaultdict[str, list[float]] = defaultdict(list)
    accelerations_by_agent: defaultdict[str, list[float]] = defaultdict(list)
    adjacent_accelerations_by_agent: defaultdict[str, list[float]] = defaultdict(list)
    sample_intervals: Counter[float] = Counter()
    gap_segment_count = 0
    gap_displacement_count = 0
    maximum_stationary_duration_s = 0.0
    isolated_stop_count = 0
    isolated_stops_by_agent: Counter[str] = Counter()
    gap_segments_by_agent: Counter[str] = Counter()
    displaced_gaps_by_agent: Counter[str] = Counter()
    stationary_duration_by_agent: defaultdict[str, float] = defaultdict(float)
    velocity_examples: list[tuple[float, _BlindVelocity]] = []
    acceleration_examples: list[tuple[float, _BlindVelocity, _BlindVelocity]] = []
    turn_examples: list[tuple[float, _BlindVelocity, _BlindVelocity]] = []
    for agent_id, points in by_agent.items():
        ordered = sorted(points, key=lambda item: (item.time_s, item.source_index))
        positive_intervals = [
            right.time_s - left.time_s
            for left, right in zip(ordered, ordered[1:], strict=False)
            if right.time_s - left.time_s > 1e-9
            and left.level_id == right.level_id
        ]
        for dt in positive_intervals:
            sample_intervals[round(dt, 6)] += 1
        cadence = _dominant_positive_interval(positive_intervals)
        velocities: list[_BlindVelocity] = []
        stationary_duration_s = 0.0
        for left, right in zip(ordered, ordered[1:], strict=False):
            dt = right.time_s - left.time_s
            if dt <= 1e-9 or left.level_id != right.level_id:
                continue
            vx = (right.x - left.x) / dt
            vy = (right.y - left.y) / dt
            speed = hypot(vx, vy)
            velocity = _BlindVelocity(
                agent_id,
                left.time_s,
                right.time_s,
                vx,
                vy,
                speed,
                left.level_id,
            )
            velocities.append(velocity)
            speeds.append(speed)
            speeds_by_agent[agent_id].append(speed)
            velocity_examples.append((speed, velocity))
            if cadence is not None and dt > cadence * 1.5 + 1e-9:
                gap_segment_count += 1
                gap_segments_by_agent[agent_id] += 1
                if hypot(right.x - left.x, right.y - left.y) > 1e-9:
                    gap_displacement_count += 1
                    displaced_gaps_by_agent[agent_id] += 1
            if speed <= active.stationary_speed_threshold_m_s:
                stationary_duration_s += dt
                maximum_stationary_duration_s = max(
                    maximum_stationary_duration_s,
                    stationary_duration_s,
                )
                stationary_duration_by_agent[agent_id] = max(
                    stationary_duration_by_agent[agent_id],
                    stationary_duration_s,
                )
            else:
                stationary_duration_s = 0.0

        for left_index, left in enumerate(velocities):
            for right in velocities[left_index + 1 :]:
                if left.level_id != right.level_id:
                    continue
                dt = right.midpoint_time_s - left.midpoint_time_s
                if dt + 1e-9 < active.acceleration_window_s:
                    continue
                acceleration = hypot(right.vx - left.vx, right.vy - left.vy) / dt
                accelerations.append(acceleration)
                accelerations_by_agent[agent_id].append(acceleration)
                acceleration_examples.append((acceleration, left, right))
                break
        for left, right in zip(velocities, velocities[1:], strict=False):
            if left.level_id != right.level_id:
                continue
            dt = right.midpoint_time_s - left.midpoint_time_s
            if dt <= 1e-9:
                continue
            acceleration = hypot(right.vx - left.vx, right.vy - left.vy) / dt
            adjacent_accelerations.append(acceleration)
            adjacent_accelerations_by_agent[agent_id].append(acceleration)
        for left, right in zip(velocities, velocities[1:], strict=False):
            if left.level_id != right.level_id:
                continue
            if min(left.speed, right.speed) < active.moving_speed_threshold_m_s:
                continue
            denominator = left.speed * right.speed
            cosine = max(
                -1.0,
                min(
                    1.0,
                    (left.vx * right.vx + left.vy * right.vy) / denominator,
                ),
            )
            angle = degrees(acos(cosine))
            turns.append(angle)
            turn_examples.append((angle, left, right))
            if (
                min(left.speed, right.speed)
                >= active.high_speed_turn_min_speed_m_s
                and angle >= active.high_speed_turn_threshold_degrees
            ):
                high_speed_turns.append(angle)
        for before, stopped, after in zip(
            velocities,
            velocities[1:],
            velocities[2:],
            strict=False,
        ):
            if (
                before.level_id == stopped.level_id == after.level_id
                and
                before.speed >= active.moving_speed_threshold_m_s
                and stopped.speed <= active.stationary_speed_threshold_m_s
                and after.speed >= active.moving_speed_threshold_m_s
            ):
                isolated_stop_count += 1
                isolated_stops_by_agent[agent_id] += 1

    speed_p99 = _percentile(speeds, 0.99)
    acceleration_p99 = _percentile(accelerations, 0.99)
    adjacent_acceleration_p99 = _percentile(adjacent_accelerations, 0.99)
    speed_p99_by_agent = {
        agent_id: value
        for agent_id, values in speeds_by_agent.items()
        if (value := _percentile(values, 0.99)) is not None
    }
    acceleration_p99_by_agent = {
        agent_id: value
        for agent_id, values in accelerations_by_agent.items()
        if (value := _percentile(values, 0.99)) is not None
    }
    maximum_agent_speed_p99 = max(speed_p99_by_agent.values(), default=None)
    maximum_agent_acceleration_p99 = max(
        acceleration_p99_by_agent.values(),
        default=None,
    )
    adjacent_acceleration_p99_by_agent = {
        agent_id: value
        for agent_id, values in adjacent_accelerations_by_agent.items()
        if (value := _percentile(values, 0.99)) is not None
    }
    maximum_agent_adjacent_acceleration_p99 = max(
        adjacent_acceleration_p99_by_agent.values(),
        default=None,
    )
    isolated_stop_fraction_by_agent = {
        agent_id: isolated_stops_by_agent.get(agent_id, 0) / max(1, len(values) - 2)
        for agent_id, values in speeds_by_agent.items()
    }
    maximum_agent_isolated_stop_fraction = max(
        isolated_stop_fraction_by_agent.values(),
        default=0.0,
    )
    large_turn_count = sum(
        angle >= active.large_turn_threshold_degrees for angle in turns
    )
    large_turn_fraction = 0.0 if not turns else large_turn_count / len(turns)
    checks = {
        "same_id_never_has_two_positions_at_once": simultaneous_dual_positions == 0,
        "different_ids_never_share_exact_position": exact_count == 0,
        "no_persistent_near_colocation": near_count == 0,
        "no_interpolated_body_overlap": swept_count == 0,
        "speed_p99_within_limit": speed_p99 is not None
        and speed_p99 <= active.max_speed_p99_m_s,
        "no_segment_exceeds_physical_speed_limit": max(speeds, default=float("inf"))
        <= active.max_segment_speed_m_s,
        "each_agent_speed_p99_within_limit": maximum_agent_speed_p99 is not None
        and maximum_agent_speed_p99 <= active.max_speed_p99_m_s,
        "acceleration_p99_within_limit": acceleration_p99 is not None
        and acceleration_p99 <= active.max_acceleration_p99_m_s2,
        "no_windowed_acceleration_exceeds_limit": max(
            accelerations,
            default=float("inf"),
        )
        <= active.max_acceleration_m_s2,
        "adjacent_acceleration_p99_within_limit": adjacent_acceleration_p99 is not None
        and adjacent_acceleration_p99
        <= active.max_adjacent_acceleration_p99_m_s2,
        "each_agent_adjacent_acceleration_p99_within_limit": (
            maximum_agent_adjacent_acceleration_p99 is not None
            and maximum_agent_adjacent_acceleration_p99
            <= active.max_acceleration_p99_m_s2
        ),
        "each_agent_acceleration_p99_within_limit": (
            maximum_agent_acceleration_p99 is not None
            and maximum_agent_acceleration_p99 <= active.max_acceleration_p99_m_s2
        ),
        "large_turn_fraction_within_limit": large_turn_fraction
        <= active.max_large_turn_fraction,
        "large_turn_absolute_count_within_limit": large_turn_count
        <= active.max_large_turn_count,
        "high_speed_turn_absolute_count_within_limit": len(high_speed_turns)
        <= active.max_high_speed_turn_count,
        "isolated_stop_fraction_within_limit": maximum_agent_isolated_stop_fraction
        <= active.max_isolated_stop_fraction,
    }
    scientific_check_names = (
        "same_id_never_has_two_positions_at_once",
        "different_ids_never_share_exact_position",
        "no_persistent_near_colocation",
        "no_interpolated_body_overlap",
        "speed_p99_within_limit",
        "no_segment_exceeds_physical_speed_limit",
        "each_agent_speed_p99_within_limit",
        "acceleration_p99_within_limit",
        "adjacent_acceleration_p99_within_limit",
        "large_turn_fraction_within_limit",
        "high_speed_turn_absolute_count_within_limit",
    )
    diagnostic_check_names = tuple(
        name for name in checks if name not in scientific_check_names
    )
    return {
        "schema_version": BLIND_TRAJECTORY_GATE_SCHEMA_VERSION,
        "passed": all(checks[name] for name in scientific_check_names),
        "scientific_check_names": list(scientific_check_names),
        "diagnostic_check_names": list(diagnostic_check_names),
        "config": asdict(active),
        "checks": checks,
        "metrics": {
            "agent_count": len(by_agent),
            "observation_count": len(truth.observations),
            "speed_p99_m_s": speed_p99,
            "speed_max_m_s": max(speeds, default=None),
            "maximum_agent_speed_p99_m_s": maximum_agent_speed_p99,
            "acceleration_p99_m_s2": acceleration_p99,
            "acceleration_max_m_s2": max(accelerations, default=None),
            "maximum_agent_acceleration_p99_m_s2": maximum_agent_acceleration_p99,
            "adjacent_acceleration_p99_m_s2": adjacent_acceleration_p99,
            "adjacent_acceleration_max_m_s2": max(adjacent_accelerations, default=None),
            "maximum_agent_adjacent_acceleration_p99_m_s2": (
                maximum_agent_adjacent_acceleration_p99
            ),
            "large_moving_turn_count": large_turn_count,
            "large_moving_turn_fraction": large_turn_fraction,
            "instantaneous_exact_colocation_count": exact_count,
            "persistent_near_colocation_count": near_count,
            "interpolated_body_overlap_pair_count": swept_count,
            "high_speed_turn_count": len(high_speed_turns),
            "same_id_dual_position_count": simultaneous_dual_positions,
            "sampling_gap_segment_count": gap_segment_count,
            "sampling_gap_with_displacement_count": gap_displacement_count,
            "maximum_stationary_duration_s": maximum_stationary_duration_s,
            "isolated_stop_sample_count": isolated_stop_count,
            "maximum_agent_isolated_stop_fraction": (
                maximum_agent_isolated_stop_fraction
            ),
            "sample_interval_histogram": dict(sorted(sample_intervals.items())),
            "acceleration_estimator": "centered_velocity_difference",
            "acceleration_window_s": active.acceleration_window_s,
            "per_agent": {
                agent_id: {
                    "speed_p99_m_s": speed_p99_by_agent.get(agent_id),
                    "speed_max_m_s": max(speeds_by_agent.get(agent_id, ()), default=None),
                    "acceleration_p99_m_s2": acceleration_p99_by_agent.get(agent_id),
                    "acceleration_max_m_s2": max(
                        accelerations_by_agent.get(agent_id, ()),
                        default=None,
                    ),
                    "adjacent_acceleration_p99_m_s2": (
                        adjacent_acceleration_p99_by_agent.get(agent_id)
                    ),
                    "adjacent_acceleration_max_m_s2": max(
                        adjacent_accelerations_by_agent.get(agent_id, ()),
                        default=None,
                    ),
                    "sampling_gap_segment_count": gap_segments_by_agent.get(agent_id, 0),
                    "sampling_gap_with_displacement_count": displaced_gaps_by_agent.get(
                        agent_id,
                        0,
                    ),
                    "maximum_stationary_duration_s": stationary_duration_by_agent.get(
                        agent_id,
                        0.0,
                    ),
                    "isolated_stop_sample_count": isolated_stops_by_agent.get(agent_id, 0),
                    "isolated_stop_fraction": isolated_stop_fraction_by_agent.get(
                        agent_id,
                        0.0,
                    ),
                }
                for agent_id in sorted(by_agent)
            },
        },
        "examples": {
            "same_id_dual_positions": dual_position_examples,
            "instantaneous_exact_colocations": exact_examples,
            "persistent_near_colocations": near_examples,
            "interpolated_body_overlaps": swept_examples,
            "highest_speeds": [
                _velocity_example(item)
                for _value, item in sorted(
                    velocity_examples,
                    key=lambda record: record[0],
                    reverse=True,
                )[: active.max_issue_examples]
            ],
            "highest_accelerations": [
                _acceleration_example(value, left, right)
                for value, left, right in sorted(
                    acceleration_examples,
                    key=lambda record: record[0],
                    reverse=True,
                )[: active.max_issue_examples]
            ],
            "largest_turns": [
                _turn_example(value, left, right)
                for value, left, right in sorted(
                    turn_examples,
                    key=lambda record: record[0],
                    reverse=True,
                )[: active.max_issue_examples]
            ],
        },
    }


def _positions_disagree(
    positions: set[tuple[float, float, str | None]],
    *,
    epsilon_m: float,
) -> bool:
    values = tuple(positions)
    return any(
        (
            left[2] is not None
            and right[2] is not None
            and left[2] != right[2]
        )
        or hypot(left[0] - right[0], left[1] - right[1]) > epsilon_m
        for index, left in enumerate(values)
        for right in values[index + 1 :]
    )


def _velocity_example(item: _BlindVelocity) -> dict[str, object]:
    return {
        "agent_id": item.agent_id,
        "start_time_s": item.start_time_s,
        "end_time_s": item.end_time_s,
        "speed_m_s": item.speed,
    }


def _acceleration_example(
    value: float,
    left: _BlindVelocity,
    right: _BlindVelocity,
) -> dict[str, object]:
    return {
        "agent_id": left.agent_id,
        "start_time_s": left.midpoint_time_s,
        "end_time_s": right.midpoint_time_s,
        "acceleration_m_s2": value,
    }


def _turn_example(
    value: float,
    left: _BlindVelocity,
    right: _BlindVelocity,
) -> dict[str, object]:
    return {
        "agent_id": left.agent_id,
        "time_s": left.end_time_s,
        "turn_degrees": value,
        "incoming_speed_m_s": left.speed,
        "outgoing_speed_m_s": right.speed,
    }


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = probability * (len(ordered) - 1)
    lower = int(rank)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _dominant_positive_interval(values: list[float]) -> float | None:
    counts = Counter(round(value, 6) for value in values if value > 1e-9)
    if not counts:
        return None
    return min(counts, key=lambda value: (-counts[value], value))


__all__ = ["BlindTrajectoryGateConfig", "analyze_blind_trajectory"]
