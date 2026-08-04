"""Build versioned visualization bundles from simulation snapshots."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from typing import Any

from ..runtime.snapshots import FrameSnapshot, TrainSnapshot
from ..runtime.simulation_clock import SimulationClock
from ..station.scenario import StationSandboxScenario


FrameInput = FrameSnapshot | Mapping[str, Any]


def _trajectory_graph_debug(
    clearance_debug: Mapping[str, Any] | None,
    agents_by_id: Mapping[int, dict[str, object]],
) -> dict[str, Any] | None:
    if clearance_debug is None:
        return None
    debug = deepcopy(dict(clearance_debug))
    passengers = debug.get("passengers")
    if not isinstance(passengers, list):
        passengers = []
        debug["passengers"] = passengers

    known_ids: set[int] = set()
    missing_trajectory_ids: list[int] = []
    for passenger in passengers:
        if not isinstance(passenger, dict):
            continue
        passenger_id = int(passenger.get("passenger_id", -1))
        known_ids.add(passenger_id)
        record = agents_by_id.get(passenger_id)
        points = record.get("points", []) if isinstance(record, dict) else []
        points = points if isinstance(points, list) else []
        physical_points = [
            point
            for point in points
            if isinstance(point, list)
            and (
                len(point) <= 9 or not isinstance(point[9], dict) or not point[9].get("visual_only")
            )
        ]
        passenger["trajectory"] = _trajectory_summary(physical_points)
        if not physical_points:
            missing_trajectory_ids.append(passenger_id)

    unexpected_trajectory_ids = sorted(set(agents_by_id) - known_ids)
    checks = debug.setdefault("checks", {})
    checks["trajectory_evidence_complete"] = (
        not missing_trajectory_ids and not unexpected_trajectory_ids
    )
    debug["missing_trajectory_ids"] = sorted(missing_trajectory_ids)
    debug["unexpected_trajectory_ids"] = unexpected_trajectory_ids
    if missing_trajectory_ids:
        debug.setdefault("blockers", []).append(
            {"code": "trajectory_evidence_missing", "evidence": sorted(missing_trajectory_ids)}
        )
    if unexpected_trajectory_ids:
        debug.setdefault("blockers", []).append(
            {"code": "trajectory_without_passenger_ledger", "evidence": unexpected_trajectory_ids}
        )
    debug["cleared"] = bool(debug.get("cleared", False)) and bool(
        checks["trajectory_evidence_complete"]
    )
    return debug


def _graph_debug_summary(graph_debug: dict[str, Any] | None) -> dict[str, Any] | None:
    if graph_debug is None:
        return None
    return {
        "schema_version": graph_debug.get("schema_version"),
        "goal_graph_mode": graph_debug.get("goal_graph_mode"),
        "graph_required": graph_debug.get("graph_required"),
        "cleared": graph_debug.get("cleared"),
        "clearance_time_s": graph_debug.get("clearance_time_s"),
        "checks": graph_debug.get("checks", {}),
        "counts": graph_debug.get("counts", {}),
        "blockers": graph_debug.get("blockers", []),
    }


def _trajectory_summary(points: list[list[Any]]) -> dict[str, Any]:
    if not points:
        return {
            "sample_count": 0,
            "first_time_s": None,
            "last_time_s": None,
            "first_position": None,
            "last_position": None,
        }
    first = points[0]
    last = points[-1]
    return {
        "sample_count": len(points),
        "first_time_s": float(first[0]),
        "last_time_s": float(last[0]),
        "first_position": [float(first[1]), float(first[2])],
        "last_position": [float(last[1]), float(last[2])],
    }


def _scenario_payload(
    scenario: StationSandboxScenario,
    final_metrics: dict[str, Any],
) -> dict[str, object]:
    design = scenario.station_design
    simulation_clock = SimulationClock.from_scenario(scenario)
    research_blockers: list[str] = []
    if not simulation_clock.research_valid:
        research_blockers.append("legacy_time_scaling")
    if not scenario.calibration_profile.research_ready:
        research_blockers.append("model_not_independently_validated")
    return {
        "station_name": scenario.station_name,
        "scenario_mode": scenario.scenario_mode,
        "hour": int(scenario.hour),
        "minutes": int(scenario.minutes),
        "demand_minutes": int(scenario.demand_duration_minutes),
        "clearance_minutes": int(scenario.clearance_minutes),
        "tick_seconds": int(scenario.tick_seconds),
        "group_size": int(scenario.group_size),
        "entry_count_hour": int(scenario.entry_count_hour),
        "exit_count_hour": int(scenario.exit_count_hour),
        "transfer_count_hour": int(scenario.transfer_count_hour),
        "source_label": scenario.source_label,
        "sample_hours": int(scenario.sample_hours),
        "movement_backend_name": scenario.movement_backend_name,
        "movement_backend": final_metrics.get("movement_backend") or scenario.movement_backend_name,
        "jupedsim_operational_model": scenario.jupedsim_operational_model,
        "jupedsim_agent_radius_m": float(scenario.jupedsim_agent_radius_units),
        "movement_trace_sample_seconds": float(scenario.movement_trace_sample_seconds),
        "simulation_clock": simulation_clock.as_dict(),
        "calibration_profile": scenario.calibration_profile.as_dict(),
        "research_readiness": {
            "ready_for_real_world_claims": not research_blockers,
            "blockers": research_blockers,
        },
        "evacuation": (
            {
                "initial_platform_persons": scenario.evacuation.initial_platform_persons,
                "alarm_delay_seconds": scenario.evacuation.alarm_delay_seconds,
                "stop_train_service": scenario.evacuation.stop_train_service,
            }
            if scenario.evacuation is not None
            else None
        ),
        "elevator_min_dispatch_persons": int(scenario.elevator_min_dispatch_persons),
        "elevator_max_dispatch_wait_seconds": float(scenario.elevator_max_dispatch_wait_seconds),
        "design_template": design.template_id if design is not None else None,
        "clock_start_seconds": int(scenario.hour) * 3600,
    }


def _train_service_payload(scenario: StationSandboxScenario) -> dict[str, object]:
    return {
        "headway_seconds": int(scenario.train_headway_seconds),
        "dwell_seconds": int(scenario.train_dwell_seconds),
        "initial_offset_seconds": int(scenario.initial_train_offset_seconds),
        "capacity_persons": int(scenario.train_capacity_persons),
        "boarding_persons_per_min": int(scenario.boarding_persons_per_min),
    }


def _run_id(
    scenario: StationSandboxScenario,
    final_metrics: dict[str, Any],
) -> str:
    design = scenario.station_design
    design_id = design.id if design is not None else "no_design"
    spawned = int(final_metrics.get("spawned_persons", 0) or 0)
    return (
        f"{design_id}:h{int(scenario.hour):02d}:"
        f"entry{int(scenario.entry_count_hour)}:"
        f"exit{int(scenario.exit_count_hour)}:"
        f"transfer{int(scenario.transfer_count_hour)}:"
        f"d{int(scenario.demand_duration_minutes)}:"
        f"m{int(scenario.minutes)}:spawned{spawned}"
    )


def _train_samples_from_frames(frames: Sequence[FrameSnapshot]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for frame in frames:
        samples.append(
            {
                "time": round(float(frame.time_seconds), 2),
                "trains": [_train_payload(train) for train in frame.trains],
            }
        )
    return samples


def _train_payload(train: TrainSnapshot) -> dict[str, object]:
    return {
        "id": train.id,
        "line_id": train.line_id,
        "direction": train.direction,
        "platform_id": train.platform_id,
        "state": train.state,
        "current_load_persons": int(train.current_load_persons),
        "last_departed_load_persons": int(train.last_departed_load_persons),
        "departure_elapsed_seconds": train.departure_elapsed_seconds,
        "departed_trains": int(train.departed_trains),
    }
