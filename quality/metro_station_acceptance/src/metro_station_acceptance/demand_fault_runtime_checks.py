from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Any

from metro_station.application.semantic_fingerprints import semantic_fingerprint
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel


def runtime_checks(
    model: MetroStationModel,
    frames: list[dict[str, Any]],
    fault: str,
) -> dict[str, bool]:
    terminal_persons = sum(event.persons for event in model.passenger_terminal_events)
    final_station = int(frames[-1]["metrics"]["station_persons"])
    checks = {
        "person_accounting_exact_each_tick": max_person_accounting_error(frames) == 0,
        "metrics_finite_and_non_negative": metrics_are_finite_non_negative(frames),
        "all_spawned_persons_terminal": terminal_persons == model.spawned_persons,
        "station_cleared": final_station == 0,
        "all_goal_graphs_complete": all(
            runtime.state.current_node_id == "complete"
            for runtime in model.passenger_goal_runtimes.values()
        ),
        "no_service_started_while_disabled": (
            model.disruption_controller.service_start_violations(model.facility_service_events) == 0
        ),
        "no_train_arrival_while_suspended": (
            model.train_disruption_controller.arrival_during_suspension_violations() == 0
        ),
    }
    checks.update(_fault_checks(model, fault))
    return checks


def runtime_metrics(
    model: MetroStationModel,
    frames: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    graph_events = Counter(
        event.kind for event in model.goal_parity.events if event.stream == "graph"
    )
    return {
        "elapsed_seconds": round(elapsed_seconds, 6),
        "frame_count": len(frames),
        "spawned_persons": model.spawned_persons,
        "terminal_persons": sum(event.persons for event in model.passenger_terminal_events),
        "remaining_persons": int(frames[-1]["metrics"]["station_persons"]),
        "max_person_accounting_error": max_person_accounting_error(frames),
        "max_station_persons": _max_metric(frames, "station_persons"),
        "max_gate_queue_persons": _max_metric(frames, "gate_queue_persons"),
        "max_vertical_queue_persons": _max_metric(frames, "vertical_queue_persons"),
        "max_crowding_index": _max_metric(frames, "crowding_index"),
        "graph_event_counts": dict(sorted(graph_events.items())),
        "spawned_persons_by_entrance": dict(sorted(model.spawned_persons_by_entrance.items())),
    }


def runtime_fingerprint(model: MetroStationModel, metrics: dict[str, Any]) -> str:
    stable_metrics = {key: value for key, value in metrics.items() if key != "elapsed_seconds"}
    return semantic_fingerprint(
        {
            "metrics": stable_metrics,
            "facility_events": model.disruption_controller.applied_event_dicts(),
            "control_events": [
                event.as_dict() for event in model.control_timeline_controller.applied_events
            ],
            "train_events": model.train_disruption_controller.applied_event_dicts(),
            "train_capacity_events": (
                model.train_disruption_controller.applied_capacity_event_dicts()
            ),
        }
    )


def max_person_accounting_error(frames: list[dict[str, Any]]) -> int:
    return max(
        (
            abs(
                int(frame["metrics"]["spawned_persons"])
                - int(frame["metrics"]["station_persons"])
                - int(frame["metrics"]["departed_persons"])
            )
            for frame in frames
        ),
        default=0,
    )


def metrics_are_finite_non_negative(frames: list[dict[str, Any]]) -> bool:
    for frame in frames:
        for value in frame["metrics"].values():
            if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
                continue
            if not isfinite(float(value)) or float(value) < 0.0:
                return False
    return True


def failure_snapshot_window(
    frames: list[dict[str, Any]],
) -> tuple[int | None, tuple[dict[str, Any], ...]]:
    for index, frame in enumerate(frames):
        metrics = frame["metrics"]
        accounting = (
            int(metrics["spawned_persons"])
            - int(metrics["station_persons"])
            - int(metrics["departed_persons"])
        )
        if accounting or not metrics_are_finite_non_negative([frame]):
            start = max(0, index - 5)
            end = min(len(frames), index + 6)
            return index, tuple(frames[start:end])
    return None, ()


def _fault_checks(model: MetroStationModel, fault: str) -> dict[str, bool]:
    if fault == "BASELINE":
        return {"no_fault_events_applied": not _all_applied_events(model)}
    if fault in {"F1-ELEVATOR", "F2-STAIRS", "F4-GATE"}:
        planned = model.scenario.facility_availability_events
        applied = model.disruption_controller.applied_events
        return {
            "facility_timeline_complete": len(applied) == len(planned),
            "facility_timeline_on_tick": all(
                event.applied_seconds == event.scheduled_seconds for event in applied
            ),
            "facility_recovered": bool(applied)
            and all(not event.effective_disabled for event in applied[len(applied) // 2 :]),
        }
    if fault == "F3-ESCALATOR":
        applied = model.control_timeline_controller.applied_events
        direction_events = [
            event for event in applied if event.measure_kind == "escalator_direction"
        ]
        return {
            "escalator_timeline_complete": len(applied) == len(model.scenario.control_plan.events),
            "escalator_timeline_on_tick": all(
                event.applied_seconds == event.scheduled_seconds for event in applied
            ),
            "safe_drain_controls_applied": all(event.status == "applied" for event in applied),
            "escalator_reverse_and_restore_applied": [event.status for event in direction_events]
            == ["applied", "applied"],
        }
    if fault == "F5A-TRAIN-FULL":
        applied = model.train_disruption_controller.applied_capacity_events
        boarding_during_restriction = [
            event
            for event in model.facility_service_events
            if event.facility_kind == "train_door" and 300.0 <= event.start_time < 540.0
        ]
        return {
            "train_capacity_timeline_complete": len(applied) == 2,
            "train_capacity_timeline_on_tick": all(
                event.applied_seconds == event.scheduled_seconds for event in applied
            ),
            "train_capacity_restored": bool(applied)
            and applied[-1].capacity_persons_after == model.scenario.train_capacity_persons,
            "no_unauthorized_boarding_during_low_capacity": not boarding_during_restriction,
        }
    applied = model.train_disruption_controller.applied_events
    return {
        "train_outage_timeline_complete": len(applied) == 2,
        "train_outage_timeline_on_tick": all(
            event.applied_seconds == event.scheduled_seconds for event in applied
        ),
        "cancelled_arrival_exercised": bool(model.train_disruption_controller.cancelled_arrivals),
        "post_recovery_arrival_exercised": any(
            float(event["time_seconds"]) >= 540.0
            for event in model.train_disruption_controller.arrivals
        ),
    }


def _all_applied_events(model: MetroStationModel) -> tuple[object, ...]:
    return (
        *model.disruption_controller.applied_events,
        *model.control_timeline_controller.applied_events,
        *model.train_disruption_controller.applied_events,
        *model.train_disruption_controller.applied_capacity_events,
    )


def _max_metric(frames: list[dict[str, Any]], name: str) -> float:
    return max((float(frame["metrics"].get(name, 0)) for frame in frames), default=0.0)
