"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station_experiments.diagnosis import diagnose_tracks
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import mesa_frames_to_visual_tracks
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from .goal_graph_acceptance_rules import (
    facility_stage_order_valid,
    replan_during_service_violations,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from .preset_trajectory_audit import audit_random_passengers


def run_preset_acceptance_case(
    *,
    preset_id: str,
    document: StationDesignDocument,
    operations: dict[str, Any],
    seed: int,
    minutes: int = 12,
    demand_minutes: int = 1,
    sample_count: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = _scenario(
        preset_id=preset_id,
        document=document,
        operations=operations,
        minutes=minutes,
        demand_minutes=demand_minutes,
    )
    started = perf_counter()
    model = MetroStationModel(scenario, seed=seed)
    frames = model.run()
    wall_seconds = perf_counter() - started

    clearance = build_clearance_debug(model)
    tracks = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=model.facilities,
        service_events=model.facility_service_events,
        terminal_events=model.passenger_terminal_events,
        clearance_debug=clearance,
        movement_trace=model.movement_backend.movement_trace(),
        facility_motion_trace=model.facility_motion_trace_recorder.as_dict(),
    )
    trajectory = diagnose_tracks(tracks)
    parity = model.goal_parity.report(model, include_events=False)
    samples = audit_random_passengers(
        model,
        document,
        sample_seed=seed + _stable_seed_offset(preset_id),
        sample_count=sample_count,
    )
    terminal_by_intent = Counter(event.intent for event in model.passenger_terminal_events)
    expected_intents = _expected_intents(scenario)
    sampled_intents = {sample["intent"] for sample in samples}
    graph_debug = tracks["graph_debug"]
    backend = model.movement_backend
    checks = {
        "passengers_spawned": model.spawned_persons > 0,
        "expected_intents_completed": all(terminal_by_intent[intent] > 0 for intent in expected_intents),
        "strict_full_clearance": bool(clearance["cleared"]),
        "clearance_checks_pass": all(clearance["checks"].values()),
        "graph_debug_checks_pass": all(graph_debug["checks"].values()),
        "graph_debug_has_no_blockers": not graph_debug["blockers"],
        "goal_physical_parity": all(parity["checks"].values()),
        "facility_stage_order_valid": facility_stage_order_valid(model),
        "no_replan_during_service": replan_during_service_violations(model) == 0,
        "trajectory_diagnosis_pass": trajectory.pass_fail == "pass",
        "sampled_trajectories_topological": bool(samples)
        and all(sample["status"] == "ok" for sample in samples),
        "sampled_intents_cover_expected": set(expected_intents) <= sampled_intents,
        "real_jupedsim_exercised": int(getattr(backend, "jps_step_count", 0)) > 0,
    }
    result = {
        "preset_id": preset_id,
        "seed": seed,
        "status": "ok" if all(checks.values()) else "review",
        "wall_seconds": round(wall_seconds, 3),
        "spawned_persons": model.spawned_persons,
        "terminal_persons": sum(event.persons for event in model.passenger_terminal_events),
        "terminal_by_intent": dict(terminal_by_intent),
        "clearance_time_s": clearance["clearance_time_s"],
        "clearance": clearance,
        "parity": parity,
        "trajectory_diagnosis": trajectory.as_dict(),
        "sampled_trajectories": samples,
        "service_event_count": len(model.facility_service_events),
        "jupedsim_steps": int(getattr(backend, "jps_step_count", 0)),
        "jupedsim_batches": int(getattr(backend, "jps_batch_count", 0)),
        "checks": checks,
    }
    return result, tracks


def _scenario(
    *,
    preset_id: str,
    document: StationDesignDocument,
    operations: dict[str, Any],
    minutes: int,
    demand_minutes: int,
) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"preset_acceptance_{preset_id}",
        hour=18,
        minutes=minutes,
        demand_minutes=demand_minutes,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=_operation_int(operations, "entry_count_hour", 180),
        exit_count_hour=_operation_int(operations, "exit_count_hour", 180),
        transfer_count_hour=_operation_int(operations, "transfer_count_hour", 0),
        source_label="station_preset_acceptance",
        sample_hours=1,
        station_design=document,
        movement_backend_name="batched_jupedsim",
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        initial_train_offset_seconds=15,
        train_headway_seconds=120,
        train_dwell_seconds=35,
        audit_enabled=False,
        audit_print_events=False,
    )


def _expected_intents(scenario: StationSandboxScenario) -> tuple[str, ...]:
    intents = ["enter_and_board", "exit_station"]
    if scenario.transfer_count_hour > 0:
        intents.append("transfer")
    return tuple(intents)


def _operation_int(operations: dict[str, Any], key: str, default: int) -> int:
    value = operations.get(key, default)
    return max(0, int(value))


def _stable_seed_offset(value: str) -> int:
    return sum((index + 1) * ord(character) for index, character in enumerate(value))
