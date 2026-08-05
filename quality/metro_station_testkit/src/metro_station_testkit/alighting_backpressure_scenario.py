from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.planning.plan import FacilityStage
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


@lru_cache(maxsize=4)
def alighting_backpressure_scenario(
    *,
    disable_exit_gates: bool = True,
    disable_entry_gates: bool = False,
) -> StationSandboxScenario:
    """Single-level deterministic scene for train-side backpressure tests.

    Disabling every downstream exit gate reproduces the decisive boundary of
    the Round-23 cycle: a source cell is physically clear while no exit-stage
    approach ownership is available.  Correct behavior retains the demand on
    the train side and publishes no passenger body.
    """

    design = create_design("single_level_terminal")
    base = StationSandboxScenario(
        station_name="testkit_alighting_backpressure",
        hour=8,
        minutes=2,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="testkit",
        sample_hours=1,
        station_design=design,
        train_headway_seconds=240,
        train_dwell_seconds=35,
        initial_train_offset_seconds=0,
        simulation_clock_mode="physical",
        alighting_source_lateral_offset_m=10.0,
        audit_enabled=True,
        audit_print_events=False,
    )
    if not disable_exit_gates and not disable_entry_gates:
        return base
    layout = DesignCompiler.compile(design, base)
    disabled_gate_ids = tuple(
        sorted(
            spec.facility_id
            for spec in layout.facilities
            if (
                disable_exit_gates
                and spec.stage == FacilityStage.EXIT_GATE.value
            )
            or (
                disable_entry_gates
                and spec.stage == FacilityStage.ENTRY_GATE.value
            )
        )
    )
    if not disabled_gate_ids:
        raise RuntimeError("backpressure micro-scene requires matching gates")
    return replace(base, disabled_facility_ids=disabled_gate_ids)


__all__ = ["alighting_backpressure_scenario"]
