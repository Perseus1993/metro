"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from metro_station.adapters.simulation.design import create_design
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station_experiments.diagnosis import diagnose_tracks
from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    mesa_frames_to_visual_tracks,
)
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from .goal_graph_acceptance_rules import (
    facility_stage_order_valid,
    replan_during_service_violations,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel


@dataclass(frozen=True)
class GoalGraphAcceptanceReport:
    layout_id: str
    seed: int
    wall_seconds: float
    spawned_persons: int
    terminal_persons: int
    active_groups: int
    completed_graphs: int
    graph_runtime_count: int
    boarded_persons: int
    departed_persons: int
    max_station_persons: int
    service_event_count: int
    jupedsim_steps: int
    jupedsim_batches: int
    terminal_by_intent: dict[str, int]
    graph_state_counts: dict[str, int]
    graph_event_counts: dict[str, int]
    clearance_checks: dict[str, bool]
    clearance_blocker_codes: tuple[str, ...]
    clearance_blockers: tuple[dict[str, object], ...]
    trajectory_status: str
    trajectory_issues: tuple[str, ...]
    trajectory_count: int
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


def run_goal_graph_acceptance(
    *,
    layout_id: str = "visual_demo_station",
    seed: int = 42,
    entry_count_hour: int = 1800,
    exit_count_hour: int = 900,
    transfer_count_hour: int = 900,
    demand_minutes: int = 5,
    clearance_minutes: int = 25,
    catalog_path: str | None = None,
    movement_backend: MovementBackend | None = None,
    station_design: StationDesignDocument | None = None,
) -> GoalGraphAcceptanceReport:
    design = create_design(layout_id) if station_design is None else station_design
    scenario = StationSandboxScenario(
        station_name=f"goal_graph_large_acceptance_{layout_id}",
        hour=18,
        minutes=demand_minutes + clearance_minutes,
        demand_minutes=demand_minutes,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=entry_count_hour,
        exit_count_hour=exit_count_hour,
        transfer_count_hour=transfer_count_hour,
        source_label="goal_graph_acceptance",
        sample_hours=1,
        station_design=design,
        movement_backend_name="jupedsim",
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        goal_graph_catalog_path=catalog_path,
        initial_train_offset_seconds=15,
        audit_enabled=False,
        audit_print_events=False,
    )
    started = perf_counter()
    model = MetroStationModel(
        scenario,
        seed=seed,
        movement_backend=movement_backend,
    )
    frames = model.run()
    wall_seconds = perf_counter() - started
    graph_states = Counter(
        runtime.state.current_node_id for runtime in model.passenger_goal_runtimes.values()
    )
    graph_events = Counter(
        transition.event_kind
        for runtime in model.passenger_goal_runtimes.values()
        for transition in runtime.transitions
    )
    terminal_by_intent = Counter(event.intent for event in model.passenger_terminal_events)
    terminal_ids = {event.passenger_id for event in model.passenger_terminal_events}
    graph_ids = set(model.passenger_goal_runtimes)
    completed_graphs = graph_states["complete"]
    backend = model.movement_backend
    max_station_persons = max(
        (frame["metrics"]["station_persons"] for frame in model.frames),
        default=0,
    )
    parity = model.goal_parity.report(model)
    parity_checks = parity["checks"]
    clearance_debug = build_clearance_debug(model)
    tracks = mesa_frames_to_visual_tracks(
        frames=frames,
        scenario=scenario,
        facilities=model.facilities,
        service_events=model.facility_service_events,
        terminal_events=model.passenger_terminal_events,
        clearance_debug=clearance_debug,
    )
    graph_debug = tracks["graph_debug"]
    trajectory = diagnose_tracks(tracks)
    checks = {
        "all_spawned_groups_have_graph": len(graph_ids) == len(terminal_ids),
        "all_spawned_persons_terminal": model.spawned_persons
        == sum(event.persons for event in model.passenger_terminal_events),
        "all_physical_journeys_terminal": not model.passengers,
        "all_graph_journeys_complete": completed_graphs == len(graph_ids),
        "graph_terminal_ids_match": graph_ids == terminal_ids,
        "facility_commitments_match": bool(parity_checks["facility_commitments_match"]),
        "graph_complete_implies_physical_terminal": bool(
            parity_checks["graph_complete_implies_physical_terminal"]
        ),
        "physical_terminal_implies_graph_complete": bool(
            parity_checks["physical_terminal_implies_graph_complete"]
        ),
        "facility_stage_order_valid": facility_stage_order_valid(model),
        "no_replan_during_service": replan_during_service_violations(model) == 0,
        "entry_exit_transfer_present": all(
            terminal_by_intent[intent] > 0
            for intent in ("enter_and_board", "exit_station", "transfer")
        ),
        "production_wait_event_exercised": graph_events["train_available"] > 0,
        "real_jupedsim_exercised": movement_backend is not None
        or int(getattr(backend, "jps_step_count", 0)) > 0,
        "crowded_peak_reached": max_station_persons >= min(50, scenario.entry_groups),
        "strict_full_clearance": bool(tracks["clearance_audit"]["cleared"]),
        "trajectory_evidence_complete": bool(graph_debug["checks"]["trajectory_evidence_complete"]),
        "trajectory_groups_match_graph_runtimes": len(tracks["agents"]) == len(graph_ids),
        "trajectory_diagnosis_pass": trajectory.pass_fail == "pass",
    }
    checks.update({f"parity_{name}": bool(value) for name, value in parity_checks.items()})
    return GoalGraphAcceptanceReport(
        layout_id=layout_id,
        seed=seed,
        wall_seconds=round(wall_seconds, 3),
        spawned_persons=model.spawned_persons,
        terminal_persons=sum(event.persons for event in model.passenger_terminal_events),
        active_groups=len(model.passengers),
        completed_graphs=completed_graphs,
        graph_runtime_count=len(graph_ids),
        boarded_persons=model.boarded_persons,
        departed_persons=model.departed_persons,
        max_station_persons=max_station_persons,
        service_event_count=len(model.facility_service_events),
        jupedsim_steps=int(getattr(backend, "jps_step_count", 0)),
        jupedsim_batches=int(getattr(backend, "jps_batch_count", 0)),
        terminal_by_intent=dict(terminal_by_intent),
        graph_state_counts=dict(graph_states),
        graph_event_counts=dict(graph_events),
        clearance_checks=dict(graph_debug["checks"]),
        clearance_blocker_codes=tuple(str(blocker["code"]) for blocker in graph_debug["blockers"]),
        clearance_blockers=tuple(dict(blocker) for blocker in graph_debug["blockers"]),
        trajectory_status=trajectory.pass_fail,
        trajectory_issues=tuple(trajectory.issues),
        trajectory_count=len(tracks["agents"]),
        checks=checks,
    )
