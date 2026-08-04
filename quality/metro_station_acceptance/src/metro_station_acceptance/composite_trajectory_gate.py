from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from math import acos, degrees, hypot, isfinite
from typing import Any

from .trajectory_truth_inputs import TrajectoryTruthInputError


COMPOSITE_TRAJECTORY_GATE_SCHEMA_VERSION = "composite_trajectory_gate_report.v1"

_WALKING_STATES = {
    "entering_station",
    "walking_to_vertical",
    "walking_to_platform",
    "walking_to_exit_gate",
    "walking_to_transfer",
}


@dataclass(frozen=True)
class CompositeTrajectoryGateConfig:
    authority_position_tolerance_m: float = 0.02
    max_speed_p99_m_s: float = 2.0
    max_segment_speed_m_s: float = 2.2
    max_acceleration_p99_m_s2: float = 4.0
    acceleration_window_s: float = 0.4
    moving_speed_threshold_m_s: float = 0.6
    large_turn_threshold_degrees: float = 150.0
    max_large_turn_fraction: float = 0.005
    hard_reversal_threshold_degrees: float = 170.0
    aba_return_tolerance_m: float = 0.12
    aba_return_max_path_ratio: float = 0.2
    duplicate_window_points: int = 12
    duplicate_window_min_displacement_m: float = 1.0
    coordinate_round_decimals: int = 3
    max_issue_examples: int = 20

    def validate(self) -> None:
        positive = (
            self.authority_position_tolerance_m,
            self.max_speed_p99_m_s,
            self.max_segment_speed_m_s,
            self.max_acceleration_p99_m_s2,
            self.acceleration_window_s,
            self.moving_speed_threshold_m_s,
            self.large_turn_threshold_degrees,
            self.hard_reversal_threshold_degrees,
            self.aba_return_tolerance_m,
            self.duplicate_window_points,
            self.duplicate_window_min_displacement_m,
            self.max_issue_examples,
        )
        if any(float(value) <= 0.0 for value in positive):
            raise ValueError("composite trajectory thresholds must be positive")
        if self.max_segment_speed_m_s < self.max_speed_p99_m_s:
            raise ValueError("max segment speed must be >= max speed p99")
        if not 0.0 <= self.max_large_turn_fraction <= 1.0:
            raise ValueError("max_large_turn_fraction must be between 0 and 1")
        if not 0 < self.large_turn_threshold_degrees <= 180:
            raise ValueError("large turn threshold must be in (0, 180]")
        if not self.large_turn_threshold_degrees <= self.hard_reversal_threshold_degrees <= 180:
            raise ValueError("hard reversal threshold must be between large turn and 180")
        if not 0 < self.aba_return_max_path_ratio <= 1:
            raise ValueError("ABA return path ratio must be in (0, 1]")
        if self.duplicate_window_points < 3:
            raise ValueError("duplicate_window_points must be >= 3")
        if self.coordinate_round_decimals < 0:
            raise ValueError("coordinate_round_decimals must be >= 0")


@dataclass(frozen=True)
class _Observation:
    agent_id: str
    time_s: float
    x: float
    y: float
    state: str
    authority: str
    source_index: int


@dataclass(frozen=True)
class _Velocity:
    agent_id: str
    start: _Observation
    end: _Observation
    vx: float
    vy: float
    speed: float

    @property
    def midpoint_time_s(self) -> float:
        return (self.start.time_s + self.end.time_s) * 0.5


def analyze_composite_trajectory(
    payload: object,
    *,
    config: CompositeTrajectoryGateConfig | None = None,
) -> dict[str, Any]:
    """Audit the visible scientific path across walking and process authorities."""

    active = config or CompositeTrajectoryGateConfig()
    active.validate()
    trace = _simulation_trace(payload)
    by_agent, boundary_issues, observation_count = _composite_observations(
        trace,
        config=active,
    )
    if not by_agent:
        raise TrajectoryTruthInputError("composite trajectory contains no passenger observations")

    velocities = _velocities(by_agent)
    speed_values = [item.speed for item in velocities]
    speed_p99 = _percentile(speed_values, 0.99)
    speed_issues = [
        _velocity_example(item)
        for item in sorted(velocities, key=lambda value: value.speed, reverse=True)
        if item.speed > active.max_segment_speed_m_s
    ]
    accelerations = _accelerations(velocities, window_s=active.acceleration_window_s)
    acceleration_values = [item[0] for item in accelerations]
    acceleration_p99 = _percentile(acceleration_values, 0.99)
    turns = _turns(velocities, moving_speed=active.moving_speed_threshold_m_s)
    large_turns = [item for item in turns if item[0] >= active.large_turn_threshold_degrees]
    hard_reversals = [
        _turn_example(item)
        for item in turns
        if item[0] >= active.hard_reversal_threshold_degrees
    ]
    large_turn_fraction = 0.0 if not turns else len(large_turns) / len(turns)
    aba_issues = _aba_issues(by_agent, velocities, config=active)
    duplicate_issues = _duplicate_path_issues(by_agent, config=active)

    checks = {
        "authority_boundaries_are_position_continuous": _count_check(
            boundary_issues,
            maximum=0,
            config=active,
        ),
        "speed_p99_within_bound": _bounded_check(
            speed_p99,
            active.max_speed_p99_m_s,
            unit="m/s",
            examples=speed_issues,
            config=active,
        ),
        "no_single_segment_exceeds_physical_speed_bound": _count_check(
            speed_issues,
            maximum=0,
            config=active,
        ),
        "acceleration_p99_within_bound": _bounded_check(
            acceleration_p99,
            active.max_acceleration_p99_m_s2,
            unit="m/s^2",
            examples=_top_acceleration_examples(accelerations, active.max_issue_examples),
            config=active,
        ),
        "large_moving_turn_fraction_within_bound": _bounded_check(
            large_turn_fraction,
            active.max_large_turn_fraction,
            unit="fraction",
            examples=[_turn_example(item) for item in large_turns],
            config=active,
        ),
        "no_hard_high_speed_reversal": _count_check(
            hard_reversals,
            maximum=0,
            config=active,
        ),
        "no_high_speed_aba_return": _count_check(
            aba_issues,
            maximum=0,
            config=active,
        ),
        "no_exact_copied_multi_point_paths": _count_check(
            duplicate_issues,
            maximum=0,
            config=active,
        ),
    }
    failed = [name for name, check in checks.items() if check["status"] == "fail"]
    return {
        "schema_version": COMPOSITE_TRAJECTORY_GATE_SCHEMA_VERSION,
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "source": {
            "authority": [
                "simulation_trace.snapshots",
                "simulation_trace.movement_trace",
                "simulation_trace.facility_motion_trace",
            ],
            "coverage": "all_passenger_states",
            "coordinate_unit": "m",
            "agent_count": len(by_agent),
            "observation_count": observation_count,
            "composite_observation_count": sum(len(items) for items in by_agent.values()),
            "presentation_samples_accepted": 0,
        },
        "configuration": asdict(active),
        "observations": {
            "velocity_sample_count": len(speed_values),
            "speed_p99_m_s": speed_p99,
            "speed_max_m_s": max(speed_values, default=None),
            "acceleration_sample_count": len(acceleration_values),
            "acceleration_p99_m_s2": acceleration_p99,
            "acceleration_max_m_s2": max(acceleration_values, default=None),
            "moving_turn_sample_count": len(turns),
            "large_moving_turn_count": len(large_turns),
            "large_moving_turn_fraction": large_turn_fraction,
            "hard_reversal_count": len(hard_reversals),
            "aba_return_count": len(aba_issues),
            "copied_path_pair_count": len(duplicate_issues),
        },
        "checks": checks,
        "summary": {"failed_checks": failed, "failed_check_count": len(failed)},
    }


def _simulation_trace(payload: object) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise TrajectoryTruthInputError("composite trajectory input must be a JSON object")
    if any(key in payload for key in ("agents", "visual_tracks", "tracks")) and not isinstance(
        payload.get("simulation_trace"), Mapping
    ):
        raise TrajectoryTruthInputError("presentation tracks cannot be composite truth input")
    trace = payload.get("simulation_trace", payload)
    if not isinstance(trace, Mapping):
        raise TrajectoryTruthInputError("simulation_trace must be an object")
    snapshots = trace.get("snapshots")
    if not _is_sequence(snapshots):
        raise TrajectoryTruthInputError("simulation_trace.snapshots must be an array")
    return trace


def _composite_observations(
    trace: Mapping[str, Any],
    *,
    config: CompositeTrajectoryGateConfig,
) -> tuple[dict[str, list[_Observation]], list[dict[str, object]], int]:
    by_key: dict[tuple[str, float], _Observation] = {}
    snapshot_by_key: dict[tuple[str, float], _Observation] = {}
    source_count = 0
    for frame_index, frame in enumerate(trace.get("snapshots", ())):
        if not isinstance(frame, Mapping):
            raise TrajectoryTruthInputError(f"snapshot {frame_index} must be an object")
        time_s = _finite_float(frame.get("time_seconds"), f"snapshot {frame_index} time")
        passengers = frame.get("passengers", ())
        if not _is_sequence(passengers):
            raise TrajectoryTruthInputError(f"snapshot {frame_index}.passengers must be an array")
        for passenger_index, passenger in enumerate(passengers):
            if not isinstance(passenger, Mapping) or "id" not in passenger:
                raise TrajectoryTruthInputError(
                    f"snapshot {frame_index} passenger {passenger_index} is invalid"
                )
            source_count += 1
            observation = _Observation(
                agent_id=str(passenger["id"]),
                time_s=time_s,
                x=_finite_float(passenger.get("x"), "snapshot passenger x"),
                y=_finite_float(passenger.get("y"), "snapshot passenger y"),
                state=str(passenger.get("state", "")),
                authority="simulation_trace.snapshots",
                source_index=source_count - 1,
            )
            key = (observation.agent_id, round(time_s, 6))
            if key in snapshot_by_key:
                raise TrajectoryTruthInputError(
                    f"duplicate snapshot observation for passenger={key[0]} time={key[1]}"
                )
            snapshot_by_key[key] = observation
            by_key[key] = observation

    boundary_issues: list[dict[str, object]] = []
    movement = trace.get("movement_trace")
    if isinstance(movement, Mapping):
        points = movement.get("points", ())
        if not _is_sequence(points):
            raise TrajectoryTruthInputError("simulation_trace.movement_trace.points must be an array")
        for point_index, point in enumerate(points):
            if not isinstance(point, Mapping):
                raise TrajectoryTruthInputError(f"movement point {point_index} must be an object")
            source_count += 1
            observation = _Observation(
                agent_id=str(point.get("passenger_id")),
                time_s=_finite_float(point.get("time_seconds"), "movement point time"),
                x=_finite_float(point.get("x"), "movement point x"),
                y=_finite_float(point.get("y"), "movement point y"),
                state="walking",
                authority="simulation_trace.movement_trace",
                source_index=point_index,
            )
            key = (observation.agent_id, round(observation.time_s, 6))
            snapshot = snapshot_by_key.get(key)
            if snapshot is not None:
                distance = hypot(observation.x - snapshot.x, observation.y - snapshot.y)
                if distance > config.authority_position_tolerance_m:
                    boundary_issues.append(
                        {
                            "agent_id": observation.agent_id,
                            "time_s": observation.time_s,
                            "distance_m": distance,
                            "snapshot_state": snapshot.state,
                            "snapshot_position": [snapshot.x, snapshot.y],
                            "movement_position": [observation.x, observation.y],
                            "reason": "same_time_authorities_disagree",
                        }
                    )
            if snapshot is None or snapshot.state in _WALKING_STATES:
                by_key[key] = observation

    facility_motion = trace.get("facility_motion_trace")
    if isinstance(facility_motion, Mapping):
        points = facility_motion.get("points", ())
        if not _is_sequence(points):
            raise TrajectoryTruthInputError(
                "simulation_trace.facility_motion_trace.points must be an array"
            )
        for point_index, point in enumerate(points):
            if not isinstance(point, Mapping):
                raise TrajectoryTruthInputError(
                    f"facility motion point {point_index} must be an object"
                )
            source_count += 1
            observation = _Observation(
                agent_id=str(point.get("passenger_id")),
                time_s=_finite_float(
                    point.get("time_seconds"),
                    "facility motion point time",
                ),
                x=_finite_float(point.get("x"), "facility motion point x"),
                y=_finite_float(point.get("y"), "facility motion point y"),
                state=str(point.get("phase", "facility_process")),
                authority="simulation_trace.facility_motion_trace",
                source_index=point_index,
            )
            key = (observation.agent_id, round(observation.time_s, 6))
            snapshot = snapshot_by_key.get(key)
            if snapshot is not None:
                distance = hypot(observation.x - snapshot.x, observation.y - snapshot.y)
                if distance > config.authority_position_tolerance_m:
                    boundary_issues.append(
                        {
                            "agent_id": observation.agent_id,
                            "time_s": observation.time_s,
                            "distance_m": distance,
                            "snapshot_state": snapshot.state,
                            "snapshot_position": [snapshot.x, snapshot.y],
                            "facility_position": [observation.x, observation.y],
                            "reason": "same_time_facility_authorities_disagree",
                        }
                    )
            by_key[key] = observation

    by_agent: defaultdict[str, list[_Observation]] = defaultdict(list)
    for observation in by_key.values():
        by_agent[observation.agent_id].append(observation)
    for observations in by_agent.values():
        observations.sort(key=lambda item: item.time_s)
    return dict(by_agent), boundary_issues, source_count


def _velocities(by_agent: Mapping[str, list[_Observation]]) -> list[_Velocity]:
    result: list[_Velocity] = []
    for agent_id, observations in sorted(by_agent.items()):
        for start, end in zip(observations, observations[1:], strict=False):
            dt = end.time_s - start.time_s
            if dt <= 1e-9:
                continue
            vx = (end.x - start.x) / dt
            vy = (end.y - start.y) / dt
            result.append(
                _Velocity(
                    agent_id=agent_id,
                    start=start,
                    end=end,
                    vx=vx,
                    vy=vy,
                    speed=hypot(vx, vy),
                )
            )
    return result


def _accelerations(
    velocities: Sequence[_Velocity],
    *,
    window_s: float,
) -> list[tuple[float, _Velocity, _Velocity]]:
    by_agent: defaultdict[str, list[_Velocity]] = defaultdict(list)
    for velocity in velocities:
        by_agent[velocity.agent_id].append(velocity)
    result: list[tuple[float, _Velocity, _Velocity]] = []
    for items in by_agent.values():
        for previous_index, previous in enumerate(items):
            for current in items[previous_index + 1 :]:
                dt = current.midpoint_time_s - previous.midpoint_time_s
                if dt + 1e-9 < window_s:
                    continue
                acceleration = hypot(current.vx - previous.vx, current.vy - previous.vy) / dt
                result.append((acceleration, previous, current))
                break
    return result


def _turns(
    velocities: Sequence[_Velocity],
    *,
    moving_speed: float,
) -> list[tuple[float, _Velocity, _Velocity]]:
    by_agent: defaultdict[str, list[_Velocity]] = defaultdict(list)
    for velocity in velocities:
        by_agent[velocity.agent_id].append(velocity)
    result: list[tuple[float, _Velocity, _Velocity]] = []
    for items in by_agent.values():
        for previous, current in zip(items, items[1:], strict=False):
            if previous.end.time_s != current.start.time_s:
                continue
            if min(previous.speed, current.speed) < moving_speed:
                continue
            cosine = (previous.vx * current.vx + previous.vy * current.vy) / (
                previous.speed * current.speed
            )
            angle = degrees(acos(max(-1.0, min(1.0, cosine))))
            result.append((angle, previous, current))
    return result


def _aba_issues(
    by_agent: Mapping[str, list[_Observation]],
    velocities: Sequence[_Velocity],
    *,
    config: CompositeTrajectoryGateConfig,
) -> list[dict[str, object]]:
    velocity_by_edge = {
        (item.agent_id, item.start.time_s, item.end.time_s): item for item in velocities
    }
    result: list[dict[str, object]] = []
    for agent_id, observations in sorted(by_agent.items()):
        for first, middle, last in zip(
            observations,
            observations[1:],
            observations[2:],
            strict=False,
        ):
            incoming = velocity_by_edge.get((agent_id, first.time_s, middle.time_s))
            outgoing = velocity_by_edge.get((agent_id, middle.time_s, last.time_s))
            if incoming is None or outgoing is None:
                continue
            if min(incoming.speed, outgoing.speed) < config.moving_speed_threshold_m_s:
                continue
            return_distance = hypot(last.x - first.x, last.y - first.y)
            if return_distance > config.aba_return_tolerance_m:
                continue
            travelled_distance = (
                hypot(middle.x - first.x, middle.y - first.y)
                + hypot(last.x - middle.x, last.y - middle.y)
            )
            if return_distance > travelled_distance * config.aba_return_max_path_ratio:
                # A small absolute displacement is not necessarily an A-B-A
                # bounce at high-rate sampling.  It may be a short avoidance
                # sidestep with meaningful forward progress.  Require the end
                # point to return close to the start relative to the detour as
                # well as in absolute metres.
                continue
            result.append(
                {
                    "agent_id": agent_id,
                    "times_s": [first.time_s, middle.time_s, last.time_s],
                    "positions": [[first.x, first.y], [middle.x, middle.y], [last.x, last.y]],
                    "return_distance_m": return_distance,
                    "travelled_distance_m": travelled_distance,
                    "return_path_ratio": (
                        return_distance / travelled_distance
                        if travelled_distance > 0
                        else 0.0
                    ),
                    "incoming_speed_m_s": incoming.speed,
                    "outgoing_speed_m_s": outgoing.speed,
                    "reason": "high_speed_return_to_previous_position",
                }
            )
    return result


def _duplicate_path_issues(
    by_agent: Mapping[str, list[_Observation]],
    *,
    config: CompositeTrajectoryGateConfig,
) -> list[dict[str, object]]:
    window_size = config.duplicate_window_points
    hashes: defaultdict[
        tuple[tuple[float, float, float], ...],
        list[tuple[str, int]],
    ] = defaultdict(list)
    for agent_id, observations in sorted(by_agent.items()):
        samples = [
            (
                round(item.time_s, config.coordinate_round_decimals),
                round(item.x, config.coordinate_round_decimals),
                round(item.y, config.coordinate_round_decimals),
            )
            for item in observations
        ]
        for start_index in range(max(0, len(samples) - window_size + 1)):
            window = tuple(samples[start_index : start_index + window_size])
            if len({(item[1], item[2]) for item in window}) < 5:
                continue
            displacement = sum(
                hypot(right[1] - left[1], right[2] - left[2])
                for left, right in zip(window, window[1:], strict=False)
            )
            if displacement < config.duplicate_window_min_displacement_m:
                continue
            hashes[window].append((agent_id, start_index))

    pair_examples: dict[tuple[str, str], dict[str, object]] = {}
    for matches in hashes.values():
        agent_ids = sorted({agent_id for agent_id, _ in matches})
        if len(agent_ids) < 2:
            continue
        first_by_agent = {agent_id: index for agent_id, index in matches}
        for left_index, left_id in enumerate(agent_ids):
            for right_id in agent_ids[left_index + 1 :]:
                pair = (left_id, right_id)
                if pair in pair_examples:
                    continue
                pair_examples[pair] = {
                    "agent_ids": [left_id, right_id],
                    "left_start_index": first_by_agent[left_id],
                    "right_start_index": first_by_agent[right_id],
                    "window_points": window_size,
                    "reason": "synchronized_exact_coordinate_window_shared_by_different_agents",
                }
    return list(pair_examples.values())


def _velocity_example(item: _Velocity) -> dict[str, object]:
    return {
        "agent_id": item.agent_id,
        "start_time_s": item.start.time_s,
        "end_time_s": item.end.time_s,
        "speed_m_s": item.speed,
        "start_authority": item.start.authority,
        "end_authority": item.end.authority,
        "start_position": [item.start.x, item.start.y],
        "end_position": [item.end.x, item.end.y],
    }


def _turn_example(item: tuple[float, _Velocity, _Velocity]) -> dict[str, object]:
    angle, previous, current = item
    return {
        "agent_id": previous.agent_id,
        "time_s": previous.end.time_s,
        "angle_degrees": angle,
        "incoming_speed_m_s": previous.speed,
        "outgoing_speed_m_s": current.speed,
        "position": [previous.end.x, previous.end.y],
    }


def _top_acceleration_examples(
    accelerations: Sequence[tuple[float, _Velocity, _Velocity]],
    limit: int,
) -> list[dict[str, object]]:
    return [
        {
            "agent_id": previous.agent_id,
            "time_s": previous.end.time_s,
            "acceleration_m_s2": acceleration,
            "incoming_speed_m_s": previous.speed,
            "outgoing_speed_m_s": current.speed,
        }
        for acceleration, previous, current in sorted(
            accelerations,
            key=lambda item: item[0],
            reverse=True,
        )[:limit]
    ]


def _count_check(
    examples: Sequence[dict[str, object]],
    *,
    maximum: int,
    config: CompositeTrajectoryGateConfig,
) -> dict[str, Any]:
    count = len(examples)
    return {
        "status": "pass" if count <= maximum else "fail",
        "hard": True,
        "count": count,
        "threshold": {"maximum": maximum},
        "examples": list(examples[: config.max_issue_examples]),
    }


def _bounded_check(
    value: float | None,
    maximum: float,
    *,
    unit: str,
    examples: Sequence[dict[str, object]],
    config: CompositeTrajectoryGateConfig,
) -> dict[str, Any]:
    passed = value is not None and value <= maximum
    return {
        "status": "pass" if passed else "fail",
        "hard": True,
        "value": value,
        "unit": unit,
        "threshold": {"maximum": maximum},
        "examples": list(examples[: config.max_issue_examples]),
    }


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = int(rank)
    upper = min(len(ordered) - 1, lower + 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _finite_float(value: object, label: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TrajectoryTruthInputError(f"{label} must be numeric") from exc
    if not isfinite(number):
        raise TrajectoryTruthInputError(f"{label} must be finite")
    return number


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)
