from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from typing import Any

from .trajectory_truth_inputs import TrajectoryTruthInputError


TRAJECTORY_KINEMATICS_GATE_SCHEMA_VERSION = "trajectory_kinematics_gate_report.v1"
_JUPEDSIM_AUTHORITIES = frozenset({"jupedsim", "jupedsim_committed_walk"})


@dataclass(frozen=True)
class KinematicPoint:
    agent_id: str
    time_s: float
    x: float
    y: float
    level_id: str | None
    episode_id: str
    sample_index: int
    source_index: int


@dataclass(frozen=True)
class TrajectoryKinematicsGateConfig:
    max_sample_interval_s: float = 0.2
    max_speed_p99_m_s: float = 2.0
    max_acceleration_p99_m_s2: float = 4.0
    acceleration_window_s: float = 0.4
    large_turn_threshold_degrees: float = 150.0
    max_large_turn_fraction: float = 0.005
    moving_speed_threshold_m_s: float = 0.2
    continuity_interval_factor: float = 1.5
    time_epsilon_s: float = 1e-9
    position_epsilon_m: float = 1e-6
    max_issue_examples: int = 20

    def validate(self) -> None:
        positive = (
            self.max_sample_interval_s,
            self.max_speed_p99_m_s,
            self.max_acceleration_p99_m_s2,
            self.acceleration_window_s,
            self.large_turn_threshold_degrees,
            self.moving_speed_threshold_m_s,
            self.continuity_interval_factor,
            self.time_epsilon_s,
            self.max_issue_examples,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("kinematic gate thresholds must be positive")
        if self.large_turn_threshold_degrees > 180.0:
            raise ValueError("large_turn_threshold_degrees must be <= 180")
        if not 0.0 <= self.max_large_turn_fraction <= 1.0:
            raise ValueError("max_large_turn_fraction must be between 0 and 1")
        if self.continuity_interval_factor < 1.0:
            raise ValueError("continuity_interval_factor must be >= 1")


@dataclass(frozen=True)
class _Velocity:
    agent_id: str
    start_time_s: float
    end_time_s: float
    vx: float
    vy: float
    speed: float
    level_id: str | None
    episode_id: str

    @property
    def midpoint_time_s(self) -> float:
        return (self.start_time_s + self.end_time_s) * 0.5


def analyze_trajectory_kinematics(
    payload: object,
    *,
    config: TrajectoryKinematicsGateConfig | None = None,
) -> dict[str, Any]:
    """Gate JuPedSim's high-rate walking trace without consuming display tracks."""

    active = config or TrajectoryKinematicsGateConfig()
    active.validate()
    points, metadata, source_kind, evidence_trace = _extract_movement_trace(payload)
    declared_interval = _required_finite_float(
        metadata.get("sample_interval_seconds"),
        "movement_trace.metadata.sample_interval_seconds",
    )
    integration_dt = _required_finite_float(
        metadata.get("integration_dt_seconds"),
        "movement_trace.metadata.integration_dt_seconds",
    )
    by_agent: defaultdict[str, list[KinematicPoint]] = defaultdict(list)
    for point in points:
        by_agent[point.agent_id].append(point)

    episode_issues = _episode_contract_issues(
        by_agent,
        declared_interval=declared_interval,
        config=active,
    )
    gap_issues, episode_transition_count = _episode_gap_evidence_issues(
        by_agent,
        evidence_trace=evidence_trace,
        config=active,
    )

    velocities, discontinuity_count = _velocities(
        by_agent,
        declared_interval=declared_interval,
        config=active,
    )
    acceleration_stride = _acceleration_stride(
        active.acceleration_window_s,
        declared_interval,
    )
    acceleration_window_s = acceleration_stride * declared_interval
    accelerations = _accelerations(
        velocities,
        declared_interval=declared_interval,
        stride=acceleration_stride,
        config=active,
    )
    turns = _turn_angles(velocities, config=active)
    speed_values = [velocity.speed for velocity in velocities]
    acceleration_values = [item[0] for item in accelerations]
    turn_values = [item[0] for item in turns]
    speed_p99 = _percentile(speed_values, 0.99)
    acceleration_p99 = _percentile(acceleration_values, 0.99)
    large_turns = [item for item in turns if item[0] >= active.large_turn_threshold_degrees]
    large_turn_fraction = 0.0 if not turns else len(large_turns) / len(turns)

    checks = {
        "high_rate_sampling": _bounded_check(
            declared_interval,
            maximum=active.max_sample_interval_s,
            unit="s",
            examples=[],
        ),
        "walking_episodes_are_contiguous": _count_check(episode_issues),
        "episode_gaps_have_simulation_evidence": _count_check(gap_issues),
        "speed_p99_within_bound": _bounded_check(
            speed_p99,
            maximum=active.max_speed_p99_m_s,
            unit="m/s",
            examples=_top_velocity_examples(velocities, active.max_issue_examples),
        ),
        "acceleration_p99_within_bound": _bounded_check(
            acceleration_p99,
            maximum=active.max_acceleration_p99_m_s2,
            unit="m/s^2",
            examples=_top_acceleration_examples(accelerations, active.max_issue_examples),
        ),
        "large_moving_turn_fraction_within_bound": _bounded_check(
            large_turn_fraction,
            maximum=active.max_large_turn_fraction,
            unit="fraction",
            examples=_top_turn_examples(large_turns, active.max_issue_examples),
        ),
    }
    failed = [name for name, check in checks.items() if check["status"] == "fail"]
    return {
        "schema_version": TRAJECTORY_KINEMATICS_GATE_SCHEMA_VERSION,
        "status": "pass" if not failed else "fail",
        "passed": not failed,
        "source": {
            "kind": source_kind,
            "authority": str(metadata.get("authority") or "jupedsim"),
            "coverage": ["walking"],
            "coordinate_unit": "m",
            "point_count": len(points),
            "agent_count": len(by_agent),
            "visual_samples_accepted": 0,
        },
        "configuration": asdict(active),
        "trace_contract": {
            "declared_sample_interval_s": declared_interval,
            "integration_dt_s": integration_dt,
            "acceleration_estimator": "centered_velocity_difference",
            "acceleration_window_s": acceleration_window_s,
            "discontinuity_count": discontinuity_count,
            "episode_transition_count": episode_transition_count,
            "episode_identity_field": "episode_id",
            "episode_sequence_field": "sample_index",
            "discontinuities_excluded_only_with_explicit_episode_boundary": True,
        },
        "observations": {
            "velocity_sample_count": len(speed_values),
            "speed_p99_m_s": speed_p99,
            "speed_max_m_s": max(speed_values, default=None),
            "acceleration_sample_count": len(acceleration_values),
            "acceleration_p99_m_s2": acceleration_p99,
            "acceleration_max_m_s2": max(acceleration_values, default=None),
            "moving_turn_sample_count": len(turn_values),
            "large_moving_turn_count": len(large_turns),
            "large_moving_turn_fraction": large_turn_fraction,
        },
        "checks": checks,
        "summary": {
            "failed_checks": failed,
            "failed_check_count": len(failed),
        },
    }


def _extract_movement_trace(
    payload: object,
) -> tuple[list[KinematicPoint], Mapping[str, Any], str, Mapping[str, Any] | None]:
    if not isinstance(payload, Mapping):
        raise TrajectoryTruthInputError("kinematic input must be a JSON object")
    replay_trace = payload.get("simulation_trace")
    if not isinstance(replay_trace, Mapping) and any(
        key in payload for key in ("visual_tracks", "agents", "tracks")
    ):
        raise TrajectoryTruthInputError("presentation tracks cannot be kinematic truth input")

    source_kind = "movement_trace"
    trace: Mapping[str, Any] = payload
    evidence_trace: Mapping[str, Any] | None = None
    if isinstance(replay_trace, Mapping):
        trace = replay_trace
        source_kind = "replay.simulation_trace.movement_trace"
        evidence_trace = replay_trace
    movement = trace.get("movement_trace")
    if isinstance(movement, Mapping):
        trace = movement
    elif str(trace.get("schema_version", "")) != "movement_trace.v1":
        raise TrajectoryTruthInputError("expected simulation_trace.movement_trace.v1")

    if str(trace.get("schema_version", "")) != "movement_trace.v1":
        raise TrajectoryTruthInputError("unsupported movement trace schema")
    metadata = trace.get("metadata")
    if not isinstance(metadata, Mapping):
        raise TrajectoryTruthInputError("movement_trace.metadata must be an object")
    if metadata.get("authority") not in _JUPEDSIM_AUTHORITIES:
        raise TrajectoryTruthInputError("movement trace authority must be jupedsim")
    if bool(metadata.get("visual_only")):
        raise TrajectoryTruthInputError("visual_only movement trace cannot be truth evidence")
    coverage = metadata.get("coverage")
    if not isinstance(coverage, Sequence) or isinstance(coverage, str | bytes):
        raise TrajectoryTruthInputError("movement trace coverage must be an array")
    if "walking" not in coverage:
        raise TrajectoryTruthInputError("movement trace must declare walking coverage")

    raw_points = trace.get("points")
    if not isinstance(raw_points, Sequence) or isinstance(raw_points, str | bytes):
        raise TrajectoryTruthInputError("movement_trace.points must be an array")
    if not raw_points:
        raise TrajectoryTruthInputError("movement_trace contains no points")
    points: list[KinematicPoint] = []
    for index, item in enumerate(raw_points):
        if not isinstance(item, Mapping):
            raise TrajectoryTruthInputError(
                f"movement point {index} must be an object"
            )
        phase = str(item.get("phase", "walking"))
        if phase not in {
            "walking",
            "passive_layout",
            "same_floor_facility",
            "elevator_boarding",
            "elevator_unloading",
            "train_door_boarding",
        }:
            raise TrajectoryTruthInputError(
                f"movement point {index} has unsupported phase {phase!r}"
            )
        if phase == "walking":
            points.append(_kinematic_point(item, index))
    if not points:
        raise TrajectoryTruthInputError("movement_trace contains no walking points")
    return points, metadata, source_kind, evidence_trace


def _kinematic_point(value: object, source_index: int) -> KinematicPoint:
    if not isinstance(value, Mapping):
        raise TrajectoryTruthInputError(f"movement point {source_index} must be an object")
    if bool(value.get("visual_only")):
        raise TrajectoryTruthInputError(f"movement point {source_index} is visual_only")
    if value.get("authority", "jupedsim") not in _JUPEDSIM_AUTHORITIES:
        raise TrajectoryTruthInputError(f"movement point {source_index} is not JuPedSim truth")
    if value.get("phase", "walking") != "walking":
        raise TrajectoryTruthInputError(f"movement point {source_index} is not walking")
    missing = [
        key
        for key in (
            "passenger_id",
            "time_seconds",
            "x",
            "y",
            "episode_id",
            "sample_index",
        )
        if key not in value
    ]
    if missing:
        raise TrajectoryTruthInputError(
            f"movement point {source_index} is missing: {', '.join(missing)}"
        )
    try:
        point = KinematicPoint(
            agent_id=str(value["passenger_id"]),
            time_s=float(value["time_seconds"]),
            x=float(value["x"]),
            y=float(value["y"]),
            level_id=None if value.get("level_id") is None else str(value["level_id"]),
            episode_id=str(value["episode_id"]),
            sample_index=int(value["sample_index"]),
            source_index=source_index,
        )
    except (TypeError, ValueError) as exc:
        raise TrajectoryTruthInputError(
            f"movement point {source_index} time/x/y must be numeric"
        ) from exc
    if not all(math.isfinite(item) for item in (point.time_s, point.x, point.y)):
        raise TrajectoryTruthInputError(f"movement point {source_index} is not finite")
    if not point.episode_id:
        raise TrajectoryTruthInputError(f"movement point {source_index} has empty episode_id")
    if point.sample_index < 0:
        raise TrajectoryTruthInputError(f"movement point {source_index} has negative sample_index")
    return point


def _episode_contract_issues(
    by_agent: Mapping[str, list[KinematicPoint]],
    *,
    declared_interval: float,
    config: TrajectoryKinematicsGateConfig,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for agent_id, points in sorted(by_agent.items()):
        closed_episodes: set[str] = set()
        current_episode: str | None = None
        previous: KinematicPoint | None = None
        for point in points:
            if point.episode_id != current_episode:
                if current_episode is not None:
                    closed_episodes.add(current_episode)
                if point.episode_id in closed_episodes:
                    issues.append(
                        {
                            "agent_id": agent_id,
                            "episode_id": point.episode_id,
                            "time_s": point.time_s,
                            "reason": "episode_id_reopened",
                        }
                    )
                if point.sample_index != 0:
                    issues.append(
                        {
                            "agent_id": agent_id,
                            "episode_id": point.episode_id,
                            "time_s": point.time_s,
                            "observed_sample_index": point.sample_index,
                            "expected_sample_index": 0,
                            "reason": "episode_does_not_start_at_zero",
                        }
                    )
                current_episode = point.episode_id
                previous = point
                continue

            assert previous is not None
            expected_index = previous.sample_index + 1
            if point.sample_index != expected_index:
                issues.append(
                    {
                        "agent_id": agent_id,
                        "episode_id": point.episode_id,
                        "time_s": point.time_s,
                        "observed_sample_index": point.sample_index,
                        "expected_sample_index": expected_index,
                        "reason": "sample_index_not_contiguous",
                    }
                )
            observed_dt = point.time_s - previous.time_s
            if abs(observed_dt - declared_interval) > config.time_epsilon_s:
                issues.append(
                    {
                        "agent_id": agent_id,
                        "episode_id": point.episode_id,
                        "time_s": point.time_s,
                        "observed_interval_s": observed_dt,
                        "expected_interval_s": declared_interval,
                        "reason": "episode_time_not_contiguous",
                    }
                )
            if point.level_id != previous.level_id:
                issues.append(
                    {
                        "agent_id": agent_id,
                        "episode_id": point.episode_id,
                        "time_s": point.time_s,
                        "reason": "level_changed_inside_episode",
                    }
                )
            previous = point
    return issues[: config.max_issue_examples]


def _episode_gap_evidence_issues(
    by_agent: Mapping[str, list[KinematicPoint]],
    *,
    evidence_trace: Mapping[str, Any] | None,
    config: TrajectoryKinematicsGateConfig,
) -> tuple[list[dict[str, object]], int]:
    transitions: list[tuple[str, KinematicPoint, KinematicPoint]] = []
    for agent_id, points in sorted(by_agent.items()):
        for previous, current in zip(points, points[1:], strict=False):
            if previous.episode_id != current.episode_id:
                transitions.append((agent_id, previous, current))
    issues: list[dict[str, object]] = []
    for agent_id, previous, current in transitions:
        same_boundary = (
            abs(current.time_s - previous.time_s) <= config.time_epsilon_s
            and current.level_id == previous.level_id
            and math.hypot(current.x - previous.x, current.y - previous.y)
            <= config.position_epsilon_m
        )
        if same_boundary:
            # Back-to-back route episodes may share their exact tick-boundary
            # anchor. This is an explicit identity transition, not an
            # unobserved temporal gap requiring snapshot/process coverage.
            continue
        if not _has_gap_evidence(
            evidence_trace,
            agent_id=agent_id,
            start_time_s=previous.time_s,
            end_time_s=current.time_s,
            epsilon_s=config.time_epsilon_s,
        ):
            issues.append(
                {
                    "agent_id": agent_id,
                    "previous_episode_id": previous.episode_id,
                    "next_episode_id": current.episode_id,
                    "start_time_s": previous.time_s,
                    "end_time_s": current.time_s,
                    "reason": "episode_boundary_has_no_snapshot_or_facility_evidence",
                }
            )
    return issues[: config.max_issue_examples], len(transitions)


_WALKING_STATES = {
    "entering_station",
    "walking_to_vertical",
    "walking_to_platform",
    "walking_to_exit_gate",
    "walking_to_transfer",
}

# The legacy coarse passenger state remains ``walking_to_*`` while the goal
# graph performs the physical queue-capture handshake.  At that point the
# passenger has reached its approach portal and is intentionally stationary;
# snapshots, rather than the walking engine, are authoritative until capture
# succeeds or replanning selects a new target.
_NON_WALKING_INTERACTION_STATES = {
    "evaluate_candidates",
    "capture_queue",
    "queueing",
    "in_service",
}


def _has_gap_evidence(
    evidence_trace: Mapping[str, Any] | None,
    *,
    agent_id: str,
    start_time_s: float,
    end_time_s: float,
    epsilon_s: float,
) -> bool:
    if evidence_trace is None:
        return False
    for event in evidence_trace.get("facility_events", ()):  # type: ignore[union-attr]
        if not isinstance(event, Mapping):
            continue
        passenger_ids = event.get("passenger_ids", ())
        if not isinstance(passenger_ids, Sequence) or isinstance(passenger_ids, str | bytes):
            continue
        if agent_id not in {str(item) for item in passenger_ids}:
            continue
        try:
            event_start = float(event["start_time"])
            event_end = float(event["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if event_start <= end_time_s + epsilon_s and event_end >= start_time_s - epsilon_s:
            return True
    for snapshot in evidence_trace.get("snapshots", ()):  # type: ignore[union-attr]
        if not isinstance(snapshot, Mapping):
            continue
        try:
            time_s = float(snapshot["time_seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if time_s < start_time_s - epsilon_s or time_s > end_time_s + epsilon_s:
            continue
        passengers = snapshot.get("passengers", ())
        if not isinstance(passengers, Sequence) or isinstance(passengers, str | bytes):
            continue
        for passenger in passengers:
            if not isinstance(passenger, Mapping) or str(passenger.get("id")) != agent_id:
                continue
            if str(passenger.get("state", "")) not in _WALKING_STATES:
                return True
            goal_graph = passenger.get("goal_graph")
            if not isinstance(goal_graph, Mapping):
                continue
            goal_state = goal_graph.get("state")
            if not isinstance(goal_state, Mapping):
                continue
            if str(goal_state.get("interaction_state", "")) in _NON_WALKING_INTERACTION_STATES:
                return True
    return False


def _velocities(
    by_agent: Mapping[str, list[KinematicPoint]],
    *,
    declared_interval: float,
    config: TrajectoryKinematicsGateConfig,
) -> tuple[list[_Velocity], int]:
    result: list[_Velocity] = []
    discontinuities = 0
    maximum_continuous_dt = declared_interval * config.continuity_interval_factor
    for agent_id, points in sorted(by_agent.items()):
        for previous, current in zip(points, points[1:], strict=False):
            dt = current.time_s - previous.time_s
            if (
                previous.episode_id != current.episode_id
                or current.sample_index != previous.sample_index + 1
                or dt <= config.time_epsilon_s
                or dt > maximum_continuous_dt + config.time_epsilon_s
                or current.level_id != previous.level_id
            ):
                discontinuities += 1
                continue
            vx = (current.x - previous.x) / dt
            vy = (current.y - previous.y) / dt
            result.append(
                _Velocity(
                    agent_id=agent_id,
                    start_time_s=previous.time_s,
                    end_time_s=current.time_s,
                    vx=vx,
                    vy=vy,
                    speed=math.hypot(vx, vy),
                    level_id=current.level_id,
                    episode_id=current.episode_id,
                )
            )
    return result, discontinuities


def _accelerations(
    velocities: list[_Velocity],
    *,
    declared_interval: float,
    stride: int,
    config: TrajectoryKinematicsGateConfig,
) -> list[tuple[float, _Velocity, _Velocity]]:
    by_agent: defaultdict[str, list[_Velocity]] = defaultdict(list)
    for velocity in velocities:
        by_agent[velocity.agent_id].append(velocity)
    result: list[tuple[float, _Velocity, _Velocity]] = []
    for items in by_agent.values():
        for index in range(stride, len(items)):
            previous = items[index - stride]
            current = items[index]
            expected_midpoint_dt = stride * declared_interval
            if (
                abs(
                    (current.midpoint_time_s - previous.midpoint_time_s)
                    - expected_midpoint_dt
                )
                > config.time_epsilon_s
                or previous.level_id != current.level_id
                or previous.episode_id != current.episode_id
            ):
                continue
            dt = current.midpoint_time_s - previous.midpoint_time_s
            if dt <= config.time_epsilon_s:
                continue
            acceleration = math.hypot(current.vx - previous.vx, current.vy - previous.vy) / dt
            result.append((acceleration, previous, current))
    return result


def _acceleration_stride(window_s: float, interval_s: float) -> int:
    return max(1, round(window_s / interval_s))


def _turn_angles(
    velocities: list[_Velocity],
    *,
    config: TrajectoryKinematicsGateConfig,
) -> list[tuple[float, _Velocity, _Velocity]]:
    by_agent: defaultdict[str, list[_Velocity]] = defaultdict(list)
    for velocity in velocities:
        by_agent[velocity.agent_id].append(velocity)
    result: list[tuple[float, _Velocity, _Velocity]] = []
    for items in by_agent.values():
        for previous, current in zip(items, items[1:], strict=False):
            if (
                abs(previous.end_time_s - current.start_time_s) > config.time_epsilon_s
                or previous.level_id != current.level_id
                or previous.episode_id != current.episode_id
                or min(previous.speed, current.speed) < config.moving_speed_threshold_m_s
            ):
                continue
            cosine = (previous.vx * current.vx + previous.vy * current.vy) / (
                previous.speed * current.speed
            )
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
            result.append((angle, previous, current))
    return result


def _bounded_check(
    observed: float | None,
    *,
    maximum: float,
    unit: str,
    examples: list[dict[str, object]],
) -> dict[str, Any]:
    passed = observed is not None and observed <= maximum
    return {
        "status": "pass" if passed else "fail",
        "hard": True,
        "observed": observed,
        "threshold": {"maximum": maximum, "unit": unit},
        "examples": examples,
    }


def _count_check(examples: list[dict[str, object]]) -> dict[str, Any]:
    return {
        "status": "pass" if not examples else "fail",
        "hard": True,
        "count": len(examples),
        "threshold": {"maximum": 0},
        "examples": examples,
    }


def _top_velocity_examples(
    velocities: list[_Velocity],
    limit: int,
) -> list[dict[str, object]]:
    return [
        {
            "agent_id": item.agent_id,
            "start_time_s": item.start_time_s,
            "end_time_s": item.end_time_s,
            "speed_m_s": item.speed,
        }
        for item in sorted(velocities, key=lambda item: item.speed, reverse=True)[:limit]
    ]


def _top_acceleration_examples(
    values: list[tuple[float, _Velocity, _Velocity]],
    limit: int,
) -> list[dict[str, object]]:
    return [
        {
            "agent_id": current.agent_id,
            "time_s": current.start_time_s,
            "acceleration_m_s2": value,
            "previous_speed_m_s": previous.speed,
            "current_speed_m_s": current.speed,
        }
        for value, previous, current in sorted(values, key=lambda item: item[0], reverse=True)[
            :limit
        ]
    ]


def _top_turn_examples(
    values: list[tuple[float, _Velocity, _Velocity]],
    limit: int,
) -> list[dict[str, object]]:
    return [
        {
            "agent_id": current.agent_id,
            "time_s": current.start_time_s,
            "turn_degrees": value,
            "previous_speed_m_s": previous.speed,
            "current_speed_m_s": current.speed,
        }
        for value, previous, current in sorted(values, key=lambda item: item[0], reverse=True)[
            :limit
        ]
    ]


def _required_finite_float(value: object, label: str) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TrajectoryTruthInputError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise TrajectoryTruthInputError(f"{label} must be finite and positive")
    return result


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
