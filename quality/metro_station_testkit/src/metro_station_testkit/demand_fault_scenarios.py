from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from metro_station.application.control_plans import (
    ACCESS_CLOSURE,
    CLOSE,
    ESCALATOR_DIRECTION,
    OPEN,
    RESTORE_DIRECTION,
    SET_DIRECTION,
    ControlEvent,
    ControlMeasure,
    ControlPlan,
)
from metro_station.adapters.simulation.planning.plan import FacilityStage
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.demand import DemandSegment
from metro_station.adapters.simulation.station.disruptions import FacilityAvailabilityEvent
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.station.train_disruptions import (
    TrainCapacityEvent,
    TrainServiceAvailabilityEvent,
)

from .demand_fault_catalog import DEMAND_PROFILES, FAULT_PROFILES
from .demand_fault_designs import TOPOLOGY_BASES, generate_demand_fault_design
from .layout_exploration_case import LayoutExplorationCase


FAULT_START_SECONDS = 300
FAULT_END_SECONDS = 540


def demand_fault_scenario(case: LayoutExplorationCase) -> StationSandboxScenario:
    topology = str(case.factors["topology"])
    demand = str(case.factors["demand"])
    fault = str(case.factors["fault"])
    if topology not in TOPOLOGY_BASES or demand not in DEMAND_PROFILES:
        raise ValueError(f"unsupported E3 factors: {topology}/{demand}")
    if fault not in {"BASELINE", *FAULT_PROFILES}:
        raise ValueError(f"unsupported E3 fault {fault!r}")
    scenario, targets = _base_scenario_and_targets(topology, demand)
    return replace(scenario, station_name=case.case_id, **_fault_overrides(fault, targets))


@lru_cache(maxsize=12)
def _base_scenario_and_targets(
    topology: str,
    demand: str,
) -> tuple[StationSandboxScenario, dict[str, tuple[str, ...]]]:
    design = generate_demand_fault_design(topology)
    entrances = tuple(
        sorted(element.id for element in design.elements if element.kind == "entrance")
    )
    scenario = StationSandboxScenario(
        station_name=f"PM028-E3-{topology}-{demand}",
        hour=8,
        minutes=25,
        tick_seconds=5,
        group_size=10,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        demand_segments=_demand_segments(demand),
        entry_entrance_weights=_entrance_weights(demand, entrances),
        source_label="PM-028-E3",
        sample_hours=1,
        station_design=design,
        train_headway_seconds=60,
        train_dwell_seconds=30,
        initial_train_offset_seconds=15,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    layout = DesignCompiler.compile(design, scenario)
    targets = {
        "elevator": _by_source_and_kind(layout.facilities, "elevator_a", "elevator"),
        "stairs": _by_source_and_kind(layout.facilities, "stairs_a", "stairs"),
        "escalator": _directional_escalator(layout.facilities),
        "gate": _half_entry_gates(layout.facilities),
        "platform": tuple(item[0] for item in layout.platform_descriptors()),
    }
    if any(not values for values in targets.values()):
        missing = sorted(name for name, values in targets.items() if not values)
        raise ValueError(f"E3 topology {topology} lacks fault targets: {', '.join(missing)}")
    return scenario, targets


def _demand_segments(demand: str) -> tuple[DemandSegment, ...]:
    if demand == "D1-SKEW":
        return (DemandSegment(0, 900, entry_count_hour=900, exit_count_hour=120),)
    if demand == "D2-COUNTER":
        return (DemandSegment(0, 900, entry_count_hour=600, exit_count_hour=600),)
    return (
        DemandSegment(0, 300, entry_count_hour=200, transfer_count_hour=200),
        DemandSegment(300, 420, entry_count_hour=200, transfer_count_hour=1200),
        DemandSegment(420, 900, entry_count_hour=200, transfer_count_hour=200),
    )


def _entrance_weights(
    demand: str,
    entrances: tuple[str, ...],
) -> tuple[tuple[str, float], ...]:
    if demand != "D1-SKEW":
        return ()
    if len(entrances) < 2:
        raise ValueError("D1-SKEW requires at least two entrances")
    return ((entrances[0], 0.9), (entrances[1], 0.1))


def _fault_overrides(fault: str, targets: dict[str, tuple[str, ...]]) -> dict[str, object]:
    if fault == "BASELINE":
        return {}
    if fault in {"F1-ELEVATOR", "F2-STAIRS", "F4-GATE"}:
        key = {"F1-ELEVATOR": "elevator", "F2-STAIRS": "stairs", "F4-GATE": "gate"}[fault]
        return {"facility_availability_events": _availability_events(targets[key])}
    if fault == "F3-ESCALATOR":
        return {"control_plan": _escalator_plan(targets["escalator"][0])}
    platform_id = targets["platform"][0]
    if fault == "F5A-TRAIN-FULL":
        return {
            "train_capacity_events": (
                TrainCapacityEvent(FAULT_START_SECONDS, platform_id, 1),
                TrainCapacityEvent(FAULT_END_SECONDS, platform_id, 1200),
            )
        }
    return {
        "train_service_events": (
            TrainServiceAvailabilityEvent(FAULT_START_SECONDS, "suspend", platform_id),
            TrainServiceAvailabilityEvent(FAULT_END_SECONDS, "resume", platform_id),
        )
    }


def _availability_events(targets: tuple[str, ...]) -> tuple[FacilityAvailabilityEvent, ...]:
    return tuple(
        FacilityAvailabilityEvent(FAULT_START_SECONDS, "disable", item) for item in targets
    ) + tuple(FacilityAvailabilityEvent(FAULT_END_SECONDS, "enable", item) for item in targets)


def _escalator_plan(facility_id: str) -> ControlPlan:
    measure_id = "reverse-escalator"
    closure_id = "drain-escalator"
    return ControlPlan(
        plan_id="pm028-e3-escalator",
        name="PM-028 E3 escalator reversal",
        measures=(
            ControlMeasure(
                measure_id=measure_id,
                kind=ESCALATOR_DIRECTION,
                label="Reverse one escalator",
                target_id=facility_id,
            ),
            ControlMeasure(
                measure_id=closure_id,
                kind=ACCESS_CLOSURE,
                label="Drain escalator before direction change",
                target_id=facility_id,
            ),
        ),
        events=(
            ControlEvent(
                event_id="drain-before-reverse",
                measure_id=closure_id,
                at_seconds=270,
                action=CLOSE,
            ),
            ControlEvent(
                event_id="reverse-at-300",
                measure_id=measure_id,
                at_seconds=FAULT_START_SECONDS,
                action=SET_DIRECTION,
                parameters={"direction": "down"},
            ),
            ControlEvent(
                event_id="reopen-after-reverse",
                measure_id=closure_id,
                at_seconds=330,
                action=OPEN,
            ),
            ControlEvent(
                event_id="drain-before-restore",
                measure_id=closure_id,
                at_seconds=510,
                action=CLOSE,
            ),
            ControlEvent(
                event_id="restore-at-540",
                measure_id=measure_id,
                at_seconds=FAULT_END_SECONDS,
                action=RESTORE_DIRECTION,
            ),
            ControlEvent(
                event_id="reopen-after-restore",
                measure_id=closure_id,
                at_seconds=570,
                action=OPEN,
            ),
        ),
    )


def _by_source_and_kind(facilities, source_id: str, kind: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            spec.facility_id
            for spec in facilities
            if spec.source_element_id == source_id and spec.kind == kind
        )
    )


def _directional_escalator(facilities) -> tuple[str, ...]:
    return tuple(
        sorted(
            spec.facility_id
            for spec in facilities
            if spec.kind == "escalator" and spec.direction == "up"
        )
    )


def _half_entry_gates(facilities) -> tuple[str, ...]:
    gates = sorted(
        spec.facility_id for spec in facilities if spec.stage == FacilityStage.ENTRY_GATE.value
    )
    return tuple(gates[: max(1, len(gates) // 2)])
