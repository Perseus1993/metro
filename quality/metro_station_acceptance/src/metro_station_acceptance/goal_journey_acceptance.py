"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station_experiments.diagnosis import diagnose_tracks
from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station.adapters.simulation.station.evacuation import (
    EVACUATION_MODE,
    EvacuationScenarioConfig,
)
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    mesa_frames_to_visual_tracks,
)
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from .goal_graph_acceptance import GoalGraphAcceptanceReport, run_goal_graph_acceptance
from .goal_graph_acceptance_rules import facility_stage_order_valid
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel


@dataclass(frozen=True)
class EvacuationAcceptanceReport:
    layout_id: str
    seed: int
    spawned_persons: int
    evacuated_persons: int
    terminal_events: int
    graph_runtimes: int
    trajectory_count: int
    clearance_checks: dict[str, bool]
    clearance_blocker_codes: tuple[str, ...]
    clearance_blockers: tuple[dict[str, object], ...]
    trajectory_status: str
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


@dataclass(frozen=True)
class FourJourneyAcceptanceReport:
    layout_id: str
    seeds: tuple[int, ...]
    normal: tuple[GoalGraphAcceptanceReport, ...]
    evacuation: tuple[EvacuationAcceptanceReport, ...]

    @property
    def status(self) -> str:
        reports = (*self.normal, *self.evacuation)
        return "ok" if reports and all(report.status == "ok" for report in reports) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "layout_id": self.layout_id,
            "seeds": self.seeds,
            "normal": [report.as_dict() for report in self.normal],
            "evacuation": [report.as_dict() for report in self.evacuation],
        }


def run_evacuation_acceptance(
    *,
    layout_id: str = "single_level_terminal",
    seed: int,
    initial_persons: int = 30,
    minutes: int = 8,
    movement_backend: MovementBackend | None = None,
    station_design: StationDesignDocument | None = None,
    trajectory_evidence: dict[str, Any] | None = None,
) -> EvacuationAcceptanceReport:
    scenario = _evacuation_scenario(
        layout_id,
        initial_persons,
        minutes,
        station_design,
    )
    model = MetroStationModel(scenario, seed=seed, movement_backend=movement_backend)
    frames = model.run()
    tracks = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=model.facilities,
        service_events=model.facility_service_events,
        terminal_events=model.passenger_terminal_events,
        clearance_debug=build_clearance_debug(model),
        movement_trace=model.movement_backend.movement_trace(),
        facility_motion_trace=model.facility_motion_trace_recorder.as_dict(),
    )
    if trajectory_evidence is not None:
        trajectory_evidence.clear()
        trajectory_evidence.update(tracks)
    graph_debug = tracks["graph_debug"]
    trajectory = diagnose_tracks(tracks)
    parity_checks = model.goal_parity.report(model, include_events=False)["checks"]
    terminal_ids = {event.passenger_id for event in model.passenger_terminal_events}
    graph_ids = set(model.passenger_goal_runtimes)
    checks = {
        "initial_population_exact": model.spawned_persons == initial_persons,
        "all_people_evacuated": model.evacuated_persons == initial_persons,
        "all_terminals_are_safe_zone": all(
            event.event == "reached_safe_zone" for event in model.passenger_terminal_events
        ),
        "graph_terminal_ids_match": graph_ids == terminal_ids,
        "all_graphs_complete": all(
            runtime.state.current_node_id == "complete"
            for runtime in model.passenger_goal_runtimes.values()
        ),
        "facility_stage_order_valid": facility_stage_order_valid(model),
        "strict_full_clearance": bool(tracks["clearance_audit"]["cleared"]),
        "trajectory_evidence_complete": bool(graph_debug["checks"]["trajectory_evidence_complete"]),
        "trajectory_groups_match_graph_runtimes": len(tracks["agents"]) == len(graph_ids),
        "trajectory_diagnosis_pass": trajectory.pass_fail == "pass",
    }
    checks.update({f"parity_{name}": bool(value) for name, value in parity_checks.items()})
    return EvacuationAcceptanceReport(
        layout_id=layout_id,
        seed=seed,
        spawned_persons=model.spawned_persons,
        evacuated_persons=model.evacuated_persons,
        terminal_events=len(model.passenger_terminal_events),
        graph_runtimes=len(model.passenger_goal_runtimes),
        trajectory_count=len(tracks["agents"]),
        clearance_checks=dict(graph_debug["checks"]),
        clearance_blocker_codes=tuple(str(blocker["code"]) for blocker in graph_debug["blockers"]),
        clearance_blockers=tuple(dict(blocker) for blocker in graph_debug["blockers"]),
        trajectory_status=trajectory.pass_fail,
        checks=checks,
    )


def run_four_journey_acceptance(
    *,
    layout_id: str = "visual_demo_station",
    seeds: tuple[int, ...] = (41, 42, 43),
    movement_backend_factory: Callable[[], MovementBackend] | None = None,
    normal_options: dict[str, int] | None = None,
    evacuation_persons: int = 30,
    evacuation_minutes: int = 8,
    station_design: StationDesignDocument | None = None,
    trajectory_evidence_by_seed: dict[int, dict[str, Any]] | None = None,
) -> FourJourneyAcceptanceReport:
    options = dict(normal_options or {})
    normal_reports: list[GoalGraphAcceptanceReport] = []
    for seed in seeds:
        evidence = {} if trajectory_evidence_by_seed is not None else None
        normal_reports.append(
            run_goal_graph_acceptance(
                layout_id=layout_id,
                seed=seed,
                movement_backend=_backend(movement_backend_factory),
                station_design=station_design,
                trajectory_evidence=evidence,
                **options,
            )
        )
        if trajectory_evidence_by_seed is not None and evidence is not None:
            trajectory_evidence_by_seed[seed] = evidence
    normal = tuple(normal_reports)
    evacuation = tuple(
        run_evacuation_acceptance(
            layout_id=layout_id,
            seed=seed,
            initial_persons=evacuation_persons,
            minutes=evacuation_minutes,
            movement_backend=_backend(movement_backend_factory),
            station_design=station_design,
        )
        for seed in seeds
    )
    return FourJourneyAcceptanceReport(
        layout_id=layout_id,
        seeds=seeds,
        normal=normal,
        evacuation=evacuation,
    )


def _evacuation_scenario(
    layout_id: str,
    initial_persons: int,
    minutes: int,
    station_design: StationDesignDocument | None,
) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"goal_graph_evacuation_acceptance_{layout_id}",
        hour=18,
        minutes=minutes,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="goal_graph_acceptance",
        sample_hours=1,
        scenario_mode=EVACUATION_MODE,
        evacuation=EvacuationScenarioConfig(initial_platform_persons=initial_persons),
        station_design=(create_design(layout_id) if station_design is None else station_design),
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _backend(
    factory: Callable[[], MovementBackend] | None,
) -> MovementBackend | None:
    return None if factory is None else factory()
