from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from scripts.analyze_metro_tracks import analyze_tracks
from scripts.analyze_vertical_trajectories import analyze_vertical
from scripts.review_decision_trajectories import review_decisions
from ..planning.plan import SERVICE_STATES
from ..runtime.contracts import diagnostic_truth_payload


@dataclass(frozen=True)
class TrajectoryThresholds:
    min_completion_rate: float = 0.8
    max_reverse_segment_share: float = 0.05
    max_stationary_duration_share: float = 0.3


@dataclass(frozen=True)
class TrajectoryReport:
    stationary_agents: int
    stationary_duration_share: float
    slow_agents: int
    bottleneck_cells: list[dict[str, Any]]
    reverse_segments: int
    teleport_segments: int
    stuck_agents: int
    anomaly_count: int
    target_jump_count: int
    far_jump_count: int
    completion_rate: float
    pass_fail: str
    issues: list[str]
    analysis_errors: dict[str, str]
    diagnosis_source: str = "trajectory_samples"
    truth_checks: dict[str, Any] = field(default_factory=dict)
    visual_checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_tracks(
    tracks_payload: dict[str, Any],
    *,
    thresholds: TrajectoryThresholds | None = None,
    input_path: Path | None = None,
) -> TrajectoryReport:
    active_thresholds = thresholds or TrajectoryThresholds()
    truth_payload = diagnostic_truth_payload(tracks_payload)
    truth_checks = _truth_checks(truth_payload)
    track_report, track_error = _run_report(
        lambda: analyze_tracks(truth_payload, input_path=input_path)
    )
    vertical_report, vertical_error = _run_report(
        lambda: analyze_vertical(truth_payload, input_path=input_path)
    )
    decision_report, decision_error = _run_report(lambda: review_decisions(truth_payload))

    analysis_errors = {
        name: error
        for name, error in (
            ("tracks", track_error),
            ("vertical", vertical_error),
            ("decision", decision_error),
        )
        if error is not None
    }

    movement = _nested(track_report, "movement", "overall")
    bottleneck = _nested(track_report, "bottleneck_grid")
    vertical_summary = _nested(vertical_report, "summary")
    decision_warnings = _nested(decision_report, "population_warnings")
    diagnosis_source = "simulation_trace" if truth_checks.get("has_simulation_trace") else "trajectory_samples"

    visual_stationary_agents = _int(movement.get("stationary_agents"))
    visual_stationary_duration_share = _float(movement.get("stationary_duration_share"))
    visual_slow_agents = _int(movement.get("slow_agents"))
    visual_bottleneck_cells = _list_of_dicts(bottleneck.get("top_cells"))
    visual_reverse_segments = _int(vertical_summary.get("reverse_segments"))
    visual_teleport_segments = _int(vertical_summary.get("jump_or_speed_segments"))
    visual_stuck_agents = _int(vertical_summary.get("stuck_agents"))
    visual_anomaly_count = _int(
        vertical_report.get("all_anomaly_count") if isinstance(vertical_report, dict) else 0
    )

    if truth_checks.get("has_simulation_trace"):
        stationary_agents = _int(truth_checks.get("remaining_agents"))
        stationary_duration_share = _float(truth_checks.get("remaining_share"))
        slow_agents = _int(truth_checks.get("service_state_remaining"))
        bottleneck_cells = _list_of_dicts(truth_checks.get("top_facility_bottlenecks"))
        reverse_segments = _int(truth_checks.get("service_event_order_errors"))
        teleport_segments = _int(truth_checks.get("missing_service_passenger_ids"))
        stuck_agents = _int(truth_checks.get("remaining_agents"))
        anomaly_count = _int(truth_checks.get("truth_anomaly_count"))
    else:
        stationary_agents = visual_stationary_agents
        stationary_duration_share = visual_stationary_duration_share
        slow_agents = visual_slow_agents
        bottleneck_cells = visual_bottleneck_cells
        reverse_segments = visual_reverse_segments
        teleport_segments = visual_teleport_segments
        stuck_agents = visual_stuck_agents
        anomaly_count = visual_anomaly_count

    target_jump_count = _target_jump_count(decision_report)
    far_jump_count = _int(decision_warnings.get("far_jump_event_count"))
    completion_rate = (
        _float(truth_checks.get("completion_rate"))
        if truth_checks.get("has_simulation_trace")
        else _completion_rate(truth_payload)
    )
    connector_segments = (
        max(1, _int(truth_checks.get("service_event_count")))
        if truth_checks.get("has_simulation_trace")
        else max(0, _int(vertical_summary.get("connector_segments")))
    )
    pass_fail, issues = _judge(
        thresholds=active_thresholds,
        completion_rate=completion_rate,
        stuck_agents=stuck_agents,
        reverse_segments=reverse_segments,
        connector_segments=connector_segments,
        stationary_duration_share=stationary_duration_share,
        anomaly_count=anomaly_count,
        analysis_errors=analysis_errors,
        diagnosis_source=diagnosis_source,
        truth_checks=truth_checks,
    )

    return TrajectoryReport(
        stationary_agents=stationary_agents,
        stationary_duration_share=stationary_duration_share,
        slow_agents=slow_agents,
        bottleneck_cells=bottleneck_cells,
        reverse_segments=reverse_segments,
        teleport_segments=teleport_segments,
        stuck_agents=stuck_agents,
        anomaly_count=anomaly_count,
        target_jump_count=target_jump_count,
        far_jump_count=far_jump_count,
        completion_rate=completion_rate,
        pass_fail=pass_fail,
        issues=issues,
        analysis_errors=analysis_errors,
        diagnosis_source=diagnosis_source,
        truth_checks=truth_checks,
        visual_checks={
            "stationary_agents": visual_stationary_agents,
            "stationary_duration_share": visual_stationary_duration_share,
            "slow_agents": visual_slow_agents,
            "bottleneck_cells": visual_bottleneck_cells,
            "reverse_segments": visual_reverse_segments,
            "teleport_segments": visual_teleport_segments,
            "stuck_agents": visual_stuck_agents,
            "anomaly_count": visual_anomaly_count,
            "target_jump_count": target_jump_count,
            "far_jump_count": far_jump_count,
        },
    )


def _run_report(callback: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    try:
        return callback(), None
    except Exception as exc:  # pragma: no cover - exercised through runner errors.
        return {}, f"{type(exc).__name__}: {exc}"


def _judge(
    *,
    thresholds: TrajectoryThresholds,
    completion_rate: float,
    stuck_agents: int,
    reverse_segments: int,
    connector_segments: int,
    stationary_duration_share: float,
    anomaly_count: int,
    analysis_errors: dict[str, str],
    diagnosis_source: str,
    truth_checks: dict[str, Any],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    reverse_share = reverse_segments / connector_segments if connector_segments else 0.0

    if analysis_errors and diagnosis_source != "simulation_trace":
        issues.append(f"analysis errors: {', '.join(sorted(analysis_errors))}")
    if truth_checks.get("service_state_remaining"):
        issues.append(f"{truth_checks['service_state_remaining']} agents remain in service states")
    if truth_checks.get("active_facility_persons"):
        issues.append(f"{truth_checks['active_facility_persons']} active facility service passengers remain")
    if truth_checks.get("service_event_order_errors"):
        issues.append(f"{truth_checks['service_event_order_errors']} invalid service event time orders")
    if truth_checks.get("missing_service_passenger_ids"):
        issues.append(f"{truth_checks['missing_service_passenger_ids']} service event passenger ids are absent from trace")
    if stuck_agents > 0:
        label = "remaining agents" if diagnosis_source == "simulation_trace" else "stuck agents in connector channels"
        issues.append(f"{stuck_agents} {label}")
    if reverse_share > thresholds.max_reverse_segment_share:
        label = "service event order error share" if diagnosis_source == "simulation_trace" else "reverse connector share"
        issues.append(f"{label} {reverse_share:.1%}")
    if completion_rate < thresholds.min_completion_rate:
        issues.append(f"completion rate {completion_rate:.1%}")

    if issues:
        return "fail", issues

    if stationary_duration_share > thresholds.max_stationary_duration_share:
        issues.append(f"stationary duration share {stationary_duration_share:.1%}")
    if anomaly_count > 0:
        issues.append(f"{anomaly_count} trajectory anomalies")
    if issues:
        return "warn", issues
    return "pass", []


def _truth_checks(tracks_payload: dict[str, Any]) -> dict[str, Any]:
    trace = tracks_payload.get("simulation_trace")
    if not isinstance(trace, dict):
        return {"has_simulation_trace": False}

    snapshots = [
        snapshot for snapshot in trace.get("snapshots", []) if isinstance(snapshot, dict)
    ]
    events = [event for event in trace.get("facility_events", []) if isinstance(event, dict)]
    aggregate = trace.get("aggregate_metrics", {})
    if not isinstance(aggregate, dict):
        aggregate = {}
    final_snapshot = snapshots[-1] if snapshots else {}
    final_metrics = final_snapshot.get("metrics", {}) if isinstance(final_snapshot, dict) else {}
    if not isinstance(final_metrics, dict):
        final_metrics = {}
    metrics = {**aggregate, **final_metrics}
    final_passengers = (
        final_snapshot.get("passengers", []) if isinstance(final_snapshot, dict) else []
    )
    final_passengers = [
        passenger for passenger in final_passengers if isinstance(passenger, dict)
    ]
    final_facilities = (
        final_snapshot.get("facilities", []) if isinstance(final_snapshot, dict) else []
    )
    final_facilities = [
        facility for facility in final_facilities if isinstance(facility, dict)
    ]

    spawned = _int(metrics.get("spawned_persons"))
    completed = _int(metrics.get("boarded_persons")) + _int(metrics.get("exit_gate_served_persons"))
    remaining = _int(metrics.get("station_persons"))
    if remaining <= 0:
        remaining = len(final_passengers)
    total = max(spawned, completed + remaining)
    completion_rate = 1.0 if total <= 0 else max(0.0, min(1.0, completed / total))
    state_counts = Counter(str(passenger.get("state", "unknown")) for passenger in final_passengers)
    service_state_remaining = sum(state_counts.get(state, 0) for state in SERVICE_STATES)
    active_facility_persons = sum(_int(facility.get("active_persons")) for facility in final_facilities)
    service_event_order_errors = sum(1 for event in events if _event_has_time_order_error(event))
    missing_service_passenger_ids = _missing_service_passenger_ids(events, snapshots)
    top_bottlenecks = _top_facility_bottlenecks(snapshots)
    truth_anomaly_count = (
        service_state_remaining
        + active_facility_persons
        + service_event_order_errors
        + missing_service_passenger_ids
    )
    return {
        "has_simulation_trace": True,
        "run_id": trace.get("run_id"),
        "snapshot_count": len(snapshots),
        "service_event_count": len(events),
        "spawned_agents": spawned,
        "completed_agents": completed,
        "remaining_agents": remaining,
        "remaining_share": 0.0 if total <= 0 else round(remaining / total, 4),
        "completion_rate": round(completion_rate, 4),
        "final_state_counts": dict(state_counts),
        "service_state_remaining": service_state_remaining,
        "active_facility_persons": active_facility_persons,
        "service_event_order_errors": service_event_order_errors,
        "missing_service_passenger_ids": missing_service_passenger_ids,
        "truth_anomaly_count": truth_anomaly_count,
        "top_facility_bottlenecks": top_bottlenecks,
    }


def _event_has_time_order_error(event: dict[str, Any]) -> bool:
    times = [
        _optional_float(event.get("start_time")),
        _optional_float(event.get("board_end_time")),
        _optional_float(event.get("arrive_time")),
        _optional_float(event.get("end_time")),
    ]
    ordered = [time for time in times if time is not None]
    return any(current < previous for previous, current in zip(ordered, ordered[1:]))


def _missing_service_passenger_ids(
    events: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> int:
    seen: set[int] = set()
    for snapshot in snapshots:
        passengers = snapshot.get("passengers", [])
        if not isinstance(passengers, list):
            continue
        for passenger in passengers:
            if not isinstance(passenger, dict):
                continue
            try:
                seen.add(int(passenger.get("id")))
            except (TypeError, ValueError):
                continue
    missing = 0
    for event in events:
        passenger_ids = event.get("passenger_ids", [])
        if not isinstance(passenger_ids, list):
            continue
        for passenger_id in passenger_ids:
            try:
                if int(passenger_id) not in seen:
                    missing += 1
            except (TypeError, ValueError):
                missing += 1
    return missing


def _top_facility_bottlenecks(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peaks: dict[str, dict[str, Any]] = {}
    durations: defaultdict[str, float] = defaultdict(float)
    previous_time: float | None = None
    previous_facilities: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        time_s = _float(snapshot.get("time_seconds"))
        dt = 0.0 if previous_time is None else max(0.0, time_s - previous_time)
        facilities = snapshot.get("facilities", [])
        if not isinstance(facilities, list):
            facilities = []
        current_facilities = {
            str(facility.get("id")): facility
            for facility in facilities
            if isinstance(facility, dict)
        }
        for facility_id, facility in previous_facilities.items():
            load = _int(facility.get("queue_persons")) + _int(facility.get("active_persons"))
            if load > 0:
                durations[facility_id] += dt
        for facility_id, facility in current_facilities.items():
            load = _int(facility.get("queue_persons")) + _int(facility.get("active_persons"))
            capacity = max(1, _int(facility.get("queue_capacity"), 1))
            pressure = load / capacity
            current_peak = peaks.get(facility_id)
            if current_peak is None or pressure > float(current_peak["pressure"]):
                peaks[facility_id] = {
                    "facility_id": facility_id,
                    "label": facility.get("label", facility_id),
                    "kind": facility.get("kind"),
                    "stage": facility.get("stage"),
                    "time_s": round(time_s, 2),
                    "load_persons": load,
                    "queue_persons": _int(facility.get("queue_persons")),
                    "active_persons": _int(facility.get("active_persons")),
                    "capacity": capacity,
                    "pressure": round(pressure, 4),
                }
        previous_time = time_s
        previous_facilities = current_facilities
    rows = []
    for facility_id, peak in peaks.items():
        row = dict(peak)
        row["loaded_duration_s"] = round(durations.get(facility_id, 0.0), 2)
        rows.append(row)
    rows.sort(
        key=lambda item: (
            -float(item["pressure"]),
            -float(item["loaded_duration_s"]),
            str(item["facility_id"]),
        )
    )
    return rows[:10]


def _completion_rate(tracks_payload: dict[str, Any]) -> float:
    clearance = tracks_payload.get("clearance_audit")
    if not isinstance(clearance, dict):
        return 0.0
    total = _int(clearance.get("total_agents"))
    if total <= 0:
        return 1.0
    completed = _int(clearance.get("completed_agents"))
    return max(0.0, min(1.0, completed / total))


def _target_jump_count(decision_report: dict[str, Any]) -> int:
    samples = decision_report.get("samples") if isinstance(decision_report, dict) else None
    if not isinstance(samples, list):
        return 0
    return sum(
        len(sample.get("target_jump_events", []))
        for sample in samples
        if isinstance(sample, dict)
    )


def _nested(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
