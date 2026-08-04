"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from metro_station_experiments.diagnosis import diagnose_tracks
from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.simulation_outputs.visual_tracks import (
    mesa_frames_to_visual_tracks,
)
from metro_station.adapters.simulation.runtime.clearance_detection import build_clearance_debug
from .goal_graph_acceptance_rules import (
    facility_stage_order_valid,
    replan_during_service_violations,
)
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from .operational_acceptance_scenarios import (
    CONGESTED,
    FACILITY_CLOSURE_RECOVERY,
    SINGLE_FACILITY,
    TRAIN_FULL_RECOVERY,
    TRAIN_OUTAGE_RECOVERY,
    operational_scenario,
)


@dataclass(frozen=True)
class OperationalAcceptanceReport:
    layout_id: str
    scenario_id: str
    seed: int
    spawned_persons: int
    terminal_persons: int
    max_station_persons: int
    max_gate_queue_persons: int
    trajectory_count: int
    graph_event_counts: dict[str, int]
    facility_events: tuple[dict[str, object], ...]
    train_events: tuple[dict[str, object], ...]
    clearance_blocker_codes: tuple[str, ...]
    clearance_blockers: tuple[dict[str, object], ...]
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


def run_operational_acceptance(
    scenario_id: str,
    *,
    layout_id: str = "visual_demo_station",
    seed: int = 42,
    movement_backend: MovementBackend | None = None,
    station_design: StationDesignDocument | None = None,
    trajectory_evidence: dict[str, Any] | None = None,
    tick_seconds: int = 1,
) -> OperationalAcceptanceReport:
    scenario = operational_scenario(
        scenario_id,
        layout_id=layout_id,
        station_design=station_design,
        tick_seconds=tick_seconds,
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
    graph_runtime_count = len(model.passenger_goal_runtimes)
    graph_events = Counter(
        event.kind for event in model.goal_parity.events if event.stream == "graph"
    )
    max_station_persons = _max_metric(frames, "station_persons")
    max_gate_queue_persons = _max_metric(frames, "gate_queue_persons")
    checks = {
        "strict_full_clearance": bool(tracks["clearance_audit"]["cleared"]),
        "trajectory_evidence_complete": bool(graph_debug["checks"]["trajectory_evidence_complete"]),
        "trajectory_groups_match_graph_runtimes": len(tracks["agents"]) == graph_runtime_count,
        "trajectory_diagnosis_pass": trajectory.pass_fail == "pass",
        "all_graphs_complete": all(
            runtime.state.current_node_id == "complete"
            for runtime in model.passenger_goal_runtimes.values()
        ),
        "facility_stage_order_valid": facility_stage_order_valid(model),
        "no_service_started_while_disabled": (
            model.disruption_controller.service_start_violations(model.facility_service_events) == 0
        ),
        "no_train_arrival_while_suspended": (
            model.train_disruption_controller.arrival_during_suspension_violations() == 0
        ),
        "no_replan_during_service": replan_during_service_violations(model) == 0,
    }
    checks.update({f"parity_{name}": bool(value) for name, value in parity_checks.items()})
    checks.update(_scenario_checks(scenario_id, model, graph_events, frames))
    return OperationalAcceptanceReport(
        layout_id=layout_id,
        scenario_id=scenario_id,
        seed=seed,
        spawned_persons=model.spawned_persons,
        terminal_persons=sum(event.persons for event in model.passenger_terminal_events),
        max_station_persons=max_station_persons,
        max_gate_queue_persons=max_gate_queue_persons,
        trajectory_count=len(tracks["agents"]),
        graph_event_counts=dict(graph_events),
        facility_events=tuple(model.disruption_controller.applied_event_dicts()),
        train_events=tuple(model.train_disruption_controller.applied_event_dicts()),
        clearance_blocker_codes=tuple(str(blocker["code"]) for blocker in graph_debug["blockers"]),
        clearance_blockers=tuple(dict(blocker) for blocker in graph_debug["blockers"]),
        checks=checks,
    )


def _scenario_checks(
    scenario_id: str,
    model: MetroStationModel,
    graph_events: Counter[str],
    frames: list[dict[str, Any]],
) -> dict[str, bool]:
    if scenario_id == SINGLE_FACILITY:
        served_ids = _served_entry_gate_ids(model)
        enabled_ids = {
            facility.facility_id
            for facility in model.gates
            if not model.disruption_controller.is_disabled(facility.facility_id)
        }
        disabled_ids = set(model.scenario.disabled_facility_ids)
        return {
            "only_enabled_entry_lane_served": served_ids <= enabled_ids,
            "single_lane_was_exercised": bool(served_ids) and len(enabled_ids) == 1,
            "disabled_lanes_never_served": not served_ids.intersection(disabled_ids),
        }
    if scenario_id == CONGESTED:
        return {
            "crowding_was_exercised": _max_metric(frames, "station_persons") >= 20,
            "gate_queue_was_exercised": _max_metric(frames, "gate_queue_persons") > 0,
        }
    if scenario_id == FACILITY_CLOSURE_RECOVERY:
        applied = model.disruption_controller.applied_events
        actions = [event.action for event in applied]
        disrupted_count = len(model.scenario.facility_availability_events) // 2
        return {
            "closure_and_recovery_applied": len(actions) == disrupted_count * 2
            and actions[:disrupted_count] == ["disable"] * disrupted_count
            and actions[disrupted_count:] == ["enable"] * disrupted_count,
            "pre_service_replan_exercised": any(
                event.passengers_replanned > 0 for event in applied
            ),
            # Planned closure is handled by the Goal Graph's explicit
            # facility-unavailable transition. Requiring progress_stalled here
            # rewards a later and less precise recovery path.
            "graph_replan_exercised": graph_events["facility_unavailable"] > 0,
        }
    if scenario_id == TRAIN_FULL_RECOVERY:
        return _train_full_recovery_checks(model, graph_events)
    if scenario_id == TRAIN_OUTAGE_RECOVERY:
        controller = model.train_disruption_controller
        return {
            "suspend_and_resume_applied": [event.action for event in controller.applied_events]
            == ["suspend", "resume"],
            "cancelled_arrival_exercised": bool(controller.cancelled_arrivals),
            "post_recovery_arrival_exercised": bool(controller.arrivals),
        }
    return {"known_scenario": False}


def _served_entry_gate_ids(model: MetroStationModel) -> set[str]:
    return {
        event.facility_id
        for event in model.facility_service_events
        if event.facility_id.startswith("entry_gate:")
    }


def _train_full_recovery_checks(
    model: MetroStationModel,
    graph_events: Counter[str],
) -> dict[str, bool]:
    events = tuple(
        event
        for event in model.goal_parity.events
        if event.stream == "graph" and event.kind == "train_full"
    )
    metadata_complete = all(
        event.train_platform_id is not None
        and event.train_arrival_sequence is not None
        for event in events
    )
    episode_keys = tuple(
        (
            int(event.passenger_id),
            str(event.train_platform_id),
            int(event.train_arrival_sequence),
        )
        for event in events
        if event.train_platform_id is not None
        and event.train_arrival_sequence is not None
    )
    train_runs = {(platform_id, sequence) for _, platform_id, sequence in episode_keys}
    return {
        "train_full_exercised": graph_events["train_full"] > 0,
        "later_train_completed_journey": model.train.departed_trains > 1,
        "train_full_episode_metadata_complete": metadata_complete,
        # Runtime polling is intentionally frequent, but one external
        # train-capacity episode is one domain fact per passenger.  Compare
        # independently propagated episode metadata, never event-id syntax.
        "train_full_episode_idempotent": (
            metadata_complete
            and graph_events["train_full"]
            == len(episode_keys)
            == len(set(episode_keys))
        ),
        "train_full_distinct_train_runs_observed": len(train_runs) >= 2,
    }


def _max_metric(frames: list[dict[str, Any]], name: str) -> int:
    return max((int(frame["metrics"].get(name, 0)) for frame in frames), default=0)
