"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.planning.plan import FacilityStage
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.disruptions import FacilityAvailabilityEvent
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.station.train_disruptions import (
    TrainServiceAvailabilityEvent,
)


SINGLE_FACILITY = "single_facility"
CONGESTED = "congested"
FACILITY_CLOSURE_RECOVERY = "facility_closure_recovery"
TRAIN_FULL_RECOVERY = "train_full_recovery"
TRAIN_OUTAGE_RECOVERY = "train_outage_recovery"
OPERATIONAL_SCENARIOS = (
    SINGLE_FACILITY,
    CONGESTED,
    FACILITY_CLOSURE_RECOVERY,
    TRAIN_FULL_RECOVERY,
    TRAIN_OUTAGE_RECOVERY,
)


def operational_scenario(
    scenario_id: str,
    *,
    layout_id: str = "visual_demo_station",
    station_design: StationDesignDocument | None = None,
    tick_seconds: int = 5,
) -> StationSandboxScenario:
    if scenario_id not in OPERATIONAL_SCENARIOS:
        raise ValueError(f"unknown operational acceptance scenario {scenario_id!r}")
    values: dict[str, object] = {
        "station_name": f"goal_graph_{layout_id}_{scenario_id}",
        "hour": 18,
        "minutes": 27,
        "demand_minutes": 2,
        "tick_seconds": tick_seconds,
        "group_size": 1,
        "entry_count_hour": 120,
        "exit_count_hour": 0,
        "transfer_count_hour": 0,
        "source_label": "operational_acceptance",
        "sample_hours": 1,
        "station_design": (create_design(layout_id) if station_design is None else station_design),
        "movement_backend_name": "jupedsim",
        "simulation_clock_mode": "physical",
        "goal_graph_mode": "active",
        "initial_train_offset_seconds": 15,
        "train_headway_seconds": 60,
        "train_dwell_seconds": 45,
        "audit_enabled": False,
        "audit_print_events": False,
    }
    scenario = StationSandboxScenario(**values)
    layout = DesignCompiler.compile(scenario.station_design, scenario)
    entry_facility_ids = tuple(
        sorted(
            spec.facility_id
            for spec in layout.facilities
            if spec.stage == FacilityStage.ENTRY_GATE.value
        )
    )
    platform_ids = tuple(item[0] for item in layout.platform_descriptors())
    return replace(
        scenario,
        **_scenario_overrides(scenario_id, entry_facility_ids, platform_ids),
    )


def _scenario_overrides(
    scenario_id: str,
    entry_facility_ids: tuple[str, ...],
    platform_ids: tuple[str, ...],
) -> dict[str, object]:
    if not entry_facility_ids:
        raise ValueError("operational acceptance requires an entry gate facility")
    if not platform_ids:
        raise ValueError("operational acceptance requires a platform")
    if scenario_id == SINGLE_FACILITY:
        return {"disabled_facility_ids": entry_facility_ids[1:]}
    if scenario_id == CONGESTED:
        return {
            "entry_count_hour": 1200,
            "gate_service_persons_per_min": 30,
        }
    if scenario_id == FACILITY_CLOSURE_RECOVERY:
        # Keep exactly one escape lane when possible.  Generated fare-control
        # banks range from two to many lanes; a fixed "first five" subset can
        # miss every active commitment in a large bank and silently fail to
        # exercise the recovery path the scenario claims to test.
        disrupted_lanes = (
            entry_facility_ids[:-1]
            if len(entry_facility_ids) > 1
            else entry_facility_ids
        )
        return {
            "entry_count_hour": 1200,
            "gate_service_persons_per_min": 6,
            "facility_availability_events": tuple(
                FacilityAvailabilityEvent(90, "disable", facility_id)
                for facility_id in disrupted_lanes
            )
            + tuple(
                FacilityAvailabilityEvent(300, "enable", facility_id)
                for facility_id in disrupted_lanes
            ),
        }
    if scenario_id == TRAIN_FULL_RECOVERY:
        return {"train_capacity_persons": 1}
    if scenario_id == TRAIN_OUTAGE_RECOVERY:
        return {
            "train_service_events": (
                TrainServiceAvailabilityEvent(0, "suspend", platform_ids[0]),
                TrainServiceAvailabilityEvent(240, "resume", platform_ids[0]),
            )
        }
    return {}
