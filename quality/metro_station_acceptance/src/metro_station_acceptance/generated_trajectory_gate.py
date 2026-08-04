from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .blind_trajectory_export import anonymized_xy_observations
from .blind_trajectory_gate import BlindTrajectoryGateConfig, analyze_blind_trajectory
from .composite_trajectory_gate import analyze_composite_trajectory
from .trajectory_kinematics_gate import analyze_trajectory_kinematics
from .trajectory_truth_gate import analyze_trajectory_truth


GENERATED_TRAJECTORY_GATE_SCHEMA_VERSION = "generated_trajectory_gate.v1"


def evaluate_generated_trajectory_gates(
    *,
    seeds: tuple[int, ...],
    normal_evidence: Mapping[int, Mapping[str, Any]],
    operational_evidence: Mapping[tuple[str, int], Mapping[str, Any]],
    operational_scenario_id: str | None,
    applicable: bool,
    not_applicable_reason: str | None = None,
) -> dict[str, Any]:
    """Evaluate every required seed without treating test doubles as science."""

    if not seeds:
        raise ValueError("generated trajectory gates require at least one seed")
    if len(seeds) != len(set(seeds)):
        raise ValueError("generated trajectory gate seeds must be unique")
    required = _required_cases(seeds, operational_scenario_id)
    if not applicable:
        return {
            "schema_version": GENERATED_TRAJECTORY_GATE_SCHEMA_VERSION,
            "status": "not_applicable",
            "applicable": False,
            "scientific_pass": None,
            "reason": not_applicable_reason or "non_scientific_movement_backend",
            "required_case_count": len(required),
            "evaluated_case_count": 0,
            "blind_observation_count": 0,
            "cases": [],
        }

    cases = [
        _evaluate_case(
            run_kind=run_kind,
            seed=seed,
            scenario_id=scenario_id,
            evidence=_case_evidence(
                run_kind,
                seed,
                scenario_id,
                normal_evidence,
                operational_evidence,
            ),
        )
        for run_kind, seed, scenario_id in required
    ]
    passed = bool(cases) and all(case["status"] == "pass" for case in cases)
    return {
        "schema_version": GENERATED_TRAJECTORY_GATE_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "applicable": True,
        "scientific_pass": passed,
        "reason": None,
        "required_case_count": len(required),
        "evaluated_case_count": sum(case["status"] != "missing" for case in cases),
        "blind_observation_count": sum(
            int(case.get("blind_observation_count", 0)) for case in cases
        ),
        "cases": cases,
    }


def _required_cases(
    seeds: tuple[int, ...],
    operational_scenario_id: str | None,
) -> tuple[tuple[str, int, str | None], ...]:
    normal = tuple(("normal", seed, None) for seed in seeds)
    if operational_scenario_id is None:
        return normal
    operational = tuple(
        ("operational", seed, operational_scenario_id) for seed in seeds
    )
    return (*normal, *operational)


def _case_evidence(
    run_kind: str,
    seed: int,
    scenario_id: str | None,
    normal_evidence: Mapping[int, Mapping[str, Any]],
    operational_evidence: Mapping[tuple[str, int], Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if run_kind == "normal":
        return normal_evidence.get(seed)
    if scenario_id is None:
        return None
    return operational_evidence.get((scenario_id, seed))


def _evaluate_case(
    *,
    run_kind: str,
    seed: int,
    scenario_id: str | None,
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    identity = {
        "run_kind": run_kind,
        "seed": seed,
        "scenario_id": scenario_id,
    }
    if evidence is None:
        return {**identity, "status": "missing", "passed": False, "gates": None}
    try:
        authority_coverage = _trajectory_authority_coverage(evidence)
        blind_observations = anonymized_xy_observations(evidence)
        gates = {
            "truth": analyze_trajectory_truth(evidence),
            "kinematics": analyze_trajectory_kinematics(evidence),
            "composite": analyze_composite_trajectory(evidence),
            "blind": analyze_blind_trajectory(
                blind_observations,
                config=_blind_config_from_evidence(evidence),
            ),
        }
    except Exception as exc:
        return {
            **identity,
            "status": "fail",
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "gates": None,
        }
    passed = bool(authority_coverage["all_state_consumers_match"]) and all(
        bool(report.get("passed")) for report in gates.values()
    )
    return {
        **identity,
        "status": "pass" if passed else "fail",
        "passed": passed,
        "blind_observation_count": len(blind_observations),
        "authority_coverage": authority_coverage,
        "gates": gates,
    }


def _trajectory_authority_coverage(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    trace = evidence.get("simulation_trace")
    if not isinstance(trace, Mapping):
        raise ValueError("simulation_trace is required for trajectory authority coverage")
    known = {
        "snapshots": "simulation_trace.snapshots",
        "movement_trace": "simulation_trace.movement_trace",
        "facility_motion_trace": "simulation_trace.facility_motion_trace",
    }
    available: list[str] = []
    observation_counts: dict[str, int] = {}
    snapshots = trace.get("snapshots")
    if isinstance(snapshots, list):
        authority = known["snapshots"]
        available.append(authority)
        observation_counts[authority] = sum(
            len(frame.get("passengers", ()))
            for frame in snapshots
            if isinstance(frame, Mapping)
            and isinstance(frame.get("passengers", ()), list)
        )
    for field in ("movement_trace", "facility_motion_trace"):
        value = trace.get(field)
        if not isinstance(value, Mapping):
            continue
        points = value.get("points", ())
        if not isinstance(points, list):
            raise ValueError(f"simulation_trace.{field}.points must be an array")
        if not points:
            continue
        authority = known[field]
        available.append(authority)
        observation_counts[authority] = len(points)
    for field, value in trace.items():
        if (
            str(field).endswith("_trace")
            and field not in known
            and isinstance(value, Mapping)
            and bool(value.get("points"))
        ):
            raise ValueError(
                f"unregistered trajectory authority simulation_trace.{field} "
                "must be wired into the scientific gates"
            )
    episode_coverage = _facility_episode_coverage(trace)
    all_state_authorities = list(available)
    expected_all_state = {
        "simulation_trace.snapshots",
        "simulation_trace.movement_trace",
    }
    if episode_coverage["facility_process_obligation_count"] > 0:
        expected_all_state.add("simulation_trace.facility_motion_trace")
    actual_all_state = set(all_state_authorities)
    consumer_sets = {
        "composite": actual_all_state,
        "blind": actual_all_state,
    }
    consumer_sets_match = (
        all(value == expected_all_state for value in consumer_sets.values())
        and episode_coverage["passed"]
    )
    return {
        "available_authorities": available,
        "observation_counts": observation_counts,
        "consumers": {
            "truth": {
                "authorities": ["simulation_trace.snapshots"],
                "coverage": "coarse_all_state_identity_and_position",
            },
            "kinematics": {
                "authorities": ["simulation_trace.movement_trace"],
                "coverage": "high_rate_walking_episodes",
            },
            "composite": {
                "authorities": all_state_authorities,
                "coverage": "all_state_authority_union",
            },
            "blind": {
                "authorities": all_state_authorities,
                "coverage": "anonymous_all_state_authority_union",
            },
        },
        "facility_episode_coverage": episode_coverage,
        "all_state_consumers_match": consumer_sets_match,
        "unknown_authority_count": 0,
    }


def _facility_episode_coverage(trace: Mapping[str, Any]) -> dict[str, Any]:
    events = trace.get("facility_events", ())
    if not isinstance(events, Sequence) or isinstance(events, str | bytes):
        raise ValueError("simulation_trace.facility_events must be an array")
    movement_points = _trace_points(trace, "movement_trace")
    facility_points = _trace_points(trace, "facility_motion_trace")
    obligations: list[dict[str, Any]] = []
    facility_process_count = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        kind = str(event.get("facility_kind", ""))
        event_id = int(event.get("event_id", -1))
        passenger_ids = event.get("passenger_ids", ())
        if not isinstance(passenger_ids, Sequence) or isinstance(
            passenger_ids, str | bytes
        ):
            continue
        start = float(event.get("start_time", 0.0))
        end = float(event.get("end_time", start))
        phases: tuple[tuple[str, str, float, float], ...]
        if kind == "gate":
            phases = (("movement_trace", "same_floor_facility", start, end),)
        elif kind in {"stairs", "escalator"}:
            phases = (("facility_motion_trace", f"{kind}_ride", start, end),)
        elif kind == "train_door":
            phases = (
                (
                    "facility_motion_trace",
                    "train_door_boarding",
                    start,
                    end,
                ),
            )
        elif kind == "elevator":
            board_end = float(event.get("board_end_time", start))
            arrive = float(event.get("arrive_time", board_end))
            phases = (
                ("movement_trace", "elevator_boarding", start, board_end),
                ("facility_motion_trace", "elevator_travel", board_end, arrive),
                ("movement_trace", "elevator_unloading", arrive, end),
            )
        else:
            continue
        for authority_field, phase, phase_start, phase_end in phases:
            if authority_field == "facility_motion_trace":
                facility_process_count += len(passenger_ids)
            source = movement_points if authority_field == "movement_trace" else facility_points
            for passenger_id in passenger_ids:
                obligations.append(
                    _check_phase_obligation(
                        source,
                        authority_field=authority_field,
                        phase=phase,
                        passenger_id=int(passenger_id),
                        event_id=event_id,
                        start_time=phase_start,
                        end_time=phase_end,
                    )
                )
    failed = [item for item in obligations if not item["passed"]]
    return {
        "passed": not failed,
        "obligation_count": len(obligations),
        "facility_process_obligation_count": facility_process_count,
        "failed_obligation_count": len(failed),
        "failed_obligations": failed,
    }


def _trace_points(trace: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    value = trace.get(field)
    if not isinstance(value, Mapping):
        return []
    points = value.get("points", ())
    if not isinstance(points, list):
        raise ValueError(f"simulation_trace.{field}.points must be an array")
    return [point for point in points if isinstance(point, Mapping)]


def _check_phase_obligation(
    points: Sequence[Mapping[str, Any]],
    *,
    authority_field: str,
    phase: str,
    passenger_id: int,
    event_id: int,
    start_time: float,
    end_time: float,
) -> dict[str, Any]:
    tolerance = 0.011
    selected = sorted(
        (
            point
            for point in points
            if int(point.get("passenger_id", -1)) == passenger_id
            and str(point.get("phase", "")) == phase
            and start_time - tolerance
            <= float(point.get("time_seconds", -1.0))
            <= end_time + tolerance
            and (
                authority_field == "movement_trace"
                or f":{event_id}:" in str(point.get("episode_id", ""))
            )
        ),
        key=lambda point: float(point["time_seconds"]),
    )
    times = [float(point["time_seconds"]) for point in selected]
    start_covered = bool(times) and abs(times[0] - start_time) <= tolerance
    end_covered = bool(times) and abs(times[-1] - end_time) <= tolerance
    max_gap = max(
        (right - left for left, right in zip(times, times[1:], strict=False)),
        default=0.0,
    )
    passed = start_covered and end_covered and max_gap <= 0.200001
    return {
        "passed": passed,
        "authority": f"simulation_trace.{authority_field}",
        "event_id": event_id,
        "passenger_id": passenger_id,
        "phase": phase,
        "start_covered": start_covered,
        "end_covered": end_covered,
        "max_gap_seconds": round(max_gap, 6),
        "observation_count": len(selected),
    }


def _blind_config_from_evidence(
    evidence: Mapping[str, Any],
) -> BlindTrajectoryGateConfig:
    trace = evidence.get("simulation_trace")
    metadata = trace.get("metadata") if isinstance(trace, Mapping) else None
    scenario = metadata.get("scenario") if isinstance(metadata, Mapping) else None
    radius = (
        scenario.get("jupedsim_agent_radius_m")
        if isinstance(scenario, Mapping)
        else None
    )
    if radius is None:
        raise ValueError(
            "simulation trace scenario metadata must declare "
            "jupedsim_agent_radius_m"
        )
    radius_m = float(radius)
    if radius_m <= 0.0:
        raise ValueError("simulation trace agent radius must be positive")
    return BlindTrajectoryGateConfig(
        maximum_near_colocation_distance_m=radius_m * 2.0,
    )


__all__ = ["evaluate_generated_trajectory_gates"]
