from __future__ import annotations

import hashlib
import json

from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.simulation import SimulationRequest

from .scenes import SceneConfig
from .scenes.designs import build_station_design


def build_metro_scenario(config: SceneConfig) -> tuple[StationSandboxScenario, str]:
    """Build the exact Metro scenario and content-address its station design."""

    design = build_station_design(config)
    design_bytes = json.dumps(
        design.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    scenario = StationSandboxScenario(
        station_name=f"alignment_{config.scene_id}",
        hour=1,
        minutes=int(config.minutes),
        tick_seconds=int(config.tick_seconds),
        group_size=1,
        entry_count_hour=int(config.entry_count_hour),
        exit_count_hour=int(config.exit_count_hour),
        source_label="alignment",
        sample_hours=1,
        entry_entrance_weights=tuple(config.entry_entrance_weights),
        simulation_clock_mode="physical",
        movement_trace_sample_seconds=float(config.movement_trace_sample_seconds),
        movement_backend_name="jupedsim",
        jupedsim_dt_seconds=float(config.jupedsim_dt_seconds),
        jupedsim_iterations_per_tick=int(config.jupedsim_iterations_per_tick),
        demand_minutes=int(config.demand_minutes),
        transfer_count_hour=0,
        station_design=design,
        jupedsim_desired_speed_mps=float(config.jupedsim_desired_speed_mps),
        jupedsim_free_speed_min_mps=float(config.jupedsim_free_speed_min_mps),
        jupedsim_free_speed_max_mps=float(config.jupedsim_free_speed_max_mps),
        alighting_source_lateral_offset_m=float(
            config.alighting_source_lateral_offset_m
        ),
        stairs_preference_share=float(config.stairs_preference_share),
        stair_fatigue_cost_up=float(config.stair_fatigue_cost_up),
        stair_fatigue_cost_down=float(config.stair_fatigue_cost_down),
        stair_bidirectional_conflict_factor=float(config.stair_bidirectional_conflict_factor),
        gate_service_persons_per_min=int(config.gate_service_persons_per_min),
        escalator_speed_units_per_tick=float(config.escalator_speed_units_per_tick),
        stairs_speed_units_per_tick=float(config.stairs_speed_units_per_tick),
        elevator_speed_units_per_tick=float(config.elevator_speed_units_per_tick),
    )
    return scenario, hashlib.sha256(design_bytes).hexdigest()


def build_metro_request(config: SceneConfig) -> tuple[SimulationRequest, str]:
    """Build the exact seeded application request used by the evidence runner."""

    scenario, design_sha256 = build_metro_scenario(config)
    return SimulationRequest(scenario=scenario, seed=int(config.seed)), design_sha256
