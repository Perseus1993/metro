from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, isfinite
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ThroughputFloor:
    """A preregistered, per-flow lower bound for one dynamic run."""

    flow_id: str
    scheduled_persons: int
    minimum_admitted_persons: int
    minimum_completed_persons: int
    evidence_ref: str
    evidence_class: str
    evidence_sha256: str
    qualification_revision: str

    def __post_init__(self) -> None:
        if not self.flow_id.strip() or not self.evidence_ref.strip():
            raise ValueError("throughput floor requires flow_id and evidence_ref")
        if self.evidence_class != "empirical_qualification":
            raise ValueError("throughput floor requires empirical_qualification evidence")
        _require_sha256(self.evidence_sha256, "throughput evidence")
        _require_git_revision(self.qualification_revision, "qualification revision")
        if self.scheduled_persons <= 0:
            raise ValueError("scheduled_persons must be positive")
        if not 0 < self.minimum_admitted_persons <= self.scheduled_persons:
            raise ValueError("minimum_admitted_persons must be in (0, scheduled]")
        if not 0 < self.minimum_completed_persons <= self.minimum_admitted_persons:
            raise ValueError("minimum_completed_persons must be in (0, minimum_admitted]")


@dataclass(frozen=True)
class ClearanceBottleneckInput:
    """Frozen input used to predict a clearance tail before executing it."""

    bottleneck_id: str
    backlog_persons: int
    minimum_service_persons_per_step: float
    downstream_tail_steps: int
    evidence_ref: str
    evidence_class: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        if not self.bottleneck_id.strip() or not self.evidence_ref.strip():
            raise ValueError("clearance input requires bottleneck_id and evidence_ref")
        if self.evidence_class not in {"analytic_proof", "held_out_qualification"}:
            raise ValueError("clearance input requires proved evidence class")
        _require_sha256(self.evidence_sha256, "clearance evidence")
        if self.backlog_persons < 0 or self.downstream_tail_steps < 0:
            raise ValueError("clearance counts and tails must be non-negative")
        rate = float(self.minimum_service_persons_per_step)
        if not isfinite(rate) or rate <= 0.0:
            raise ValueError("minimum service rate must be finite and positive")

    @property
    def predicted_steps(self) -> int:
        service_steps = ceil(self.backlog_persons / self.minimum_service_persons_per_step)
        return int(service_steps + self.downstream_tail_steps)


def preregister_clearance_prediction(
    inputs: Sequence[ClearanceBottleneckInput],
    *,
    pipeline_proved: bool,
    pipeline_evidence_ref: str | None = None,
    pipeline_evidence_sha256: str | None = None,
) -> dict[str, Any]:
    """Freeze a derived tail; an empty evidence set is explicitly unavailable."""

    if not inputs:
        return {
            "schema_version": "alignment_round27_clearance_prediction.v1",
            "status": "prediction_unavailable",
            "reason": "no proved minimum service rate inputs",
            "pipeline_proved": bool(pipeline_proved),
            "bottlenecks": [],
            "predicted_clearance_upper_steps": None,
        }
    if pipeline_proved:
        if not pipeline_evidence_ref or not pipeline_evidence_ref.strip():
            raise ValueError("pipeline proof requires an evidence reference")
        _require_sha256(pipeline_evidence_sha256, "pipeline evidence")
    rows = [
        {**asdict(item), "predicted_steps": item.predicted_steps}
        for item in inputs
    ]
    upper = (
        max(item.predicted_steps for item in inputs)
        if pipeline_proved
        else sum(item.predicted_steps for item in inputs)
    )
    return {
        "schema_version": "alignment_round27_clearance_prediction.v1",
        "status": "preregistered",
        "pipeline_proved": bool(pipeline_proved),
        "composition": "maximum" if pipeline_proved else "conservative_serial_sum",
        "pipeline_evidence_ref": pipeline_evidence_ref,
        "pipeline_evidence_sha256": pipeline_evidence_sha256,
        "bottlenecks": rows,
        "predicted_clearance_upper_steps": int(upper),
    }


def evaluate_dynamic_gate(
    boundaries: Mapping[str, Mapping[str, Any]],
    floors: Sequence[ThroughputFloor],
    *,
    run_outcome_code: str | None,
    liveness_violations: int,
    round26_replan_ratio: float,
    round26_placement_retry_ratio: float,
) -> dict[str, Any]:
    """Require useful service while allowing an external entry backlog."""

    checks: list[dict[str, Any]] = [
        _check("run_outcome_success", run_outcome_code, None, "==")
    ]
    floor_by_flow = {floor.flow_id: floor for floor in floors}
    if len(floor_by_flow) != len(floors):
        raise ValueError("dynamic throughput floors require unique flow ids")
    for flow_id, floor in floor_by_flow.items():
        metrics = boundaries.get(flow_id)
        if metrics is None:
            checks.append(_check(f"{flow_id}.present", False, True, "=="))
            continue
        scheduled = _integer(metrics, "scheduled_persons")
        waiting = _integer(metrics, "source_waiting_persons")
        active = _integer(metrics, "active_inside_persons")
        completed = _integer(metrics, "completed_persons")
        not_alighted = _integer(metrics, "not_alighted_persons")
        dropped = _integer(metrics, "dropped_persons")
        admitted = _integer(metrics, "admitted_persons")
        checks.extend(
            [
                _check(f"{flow_id}.scheduled_frozen", scheduled, floor.scheduled_persons, "=="),
                _check(
                    f"{flow_id}.admission_floor",
                    admitted,
                    floor.minimum_admitted_persons,
                    ">=",
                ),
                _check(
                    f"{flow_id}.completion_floor",
                    completed,
                    floor.minimum_completed_persons,
                    ">=",
                ),
                _check(f"{flow_id}.dropped_zero", dropped, 0, "=="),
                _check(
                    f"{flow_id}.conserved",
                    scheduled,
                    waiting + active + completed + not_alighted + dropped,
                    "==",
                ),
            ]
        )
    checks.append(_check("passenger_liveness_zero", liveness_violations, 0, "=="))
    checks.append(_check("round26_replan_not_regressed", round26_replan_ratio, 0.01, "<="))
    checks.append(
        _check(
            "round26_placement_retry_not_regressed",
            round26_placement_retry_ratio,
            0.01,
            "<=",
        )
    )
    return _report("alignment_round27_dynamic_gate.v1", checks, floors=floors)


def evaluate_clearance_gate(
    *,
    prediction: Mapping[str, Any],
    observed_clearance_steps: int | None,
    source_waiting_persons: int,
    active_inside_persons: int,
    queue_persons: int,
    owner_persons: int,
    dropped_persons: int,
    flow_conserved: bool,
    liveness_violations: int,
    run_outcome_code: str | None,
    scheduled_alighting_persons: int,
    expected_train_runs: int,
    train_manifests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate a pre-derived clearance bound and the train physical invariant."""

    upper = prediction.get("predicted_clearance_upper_steps")
    available = prediction.get("status") == "preregistered" and isinstance(upper, int)
    checks = [
        _check("prediction_available", available, True, "=="),
        _check("source_waiting_zero", source_waiting_persons, 0, "=="),
        _check("active_inside_zero", active_inside_persons, 0, "=="),
        _check("queue_persons_zero", queue_persons, 0, "=="),
        _check("owner_persons_zero", owner_persons, 0, "=="),
        _check("dropped_zero", dropped_persons, 0, "=="),
        _check("flow_conserved", flow_conserved, True, "=="),
        _check("liveness_zero", liveness_violations, 0, "=="),
        _check("run_outcome_success", run_outcome_code, None, "=="),
        _check("train_manifest_count", len(train_manifests), expected_train_runs, "=="),
        _check(
            "alighting_manifest_nonvacuous",
            expected_train_runs > 0,
            scheduled_alighting_persons > 0,
            "==",
        ),
    ]
    tail_pass = (
        available
        and isinstance(observed_clearance_steps, int)
        and observed_clearance_steps <= int(upper)
    )
    checks.append(
        _check(
            "clearance_within_prediction",
            observed_clearance_steps,
            upper,
            "<=",
            forced=tail_pass,
        )
    )
    for index, manifest in enumerate(train_manifests):
        prefix = f"train_manifest[{index}]"
        status = str(manifest.get("departure_status", ""))
        released = _integer(manifest, "released_alight_persons")
        planned = _integer(manifest, "planned_alight_persons")
        complete_step = manifest.get("alighting_release_complete_step")
        departure_step = manifest.get("actual_departure_step")
        checks.extend(
            [
                _check(f"{prefix}.departed", status, "departed", "=="),
                _check(f"{prefix}.alighting_complete", released, planned, "=="),
                _check(f"{prefix}.not_alighted_zero", _integer(manifest, "not_alighted_persons"), 0, "=="),
                _check(
                    f"{prefix}.complete_before_departure",
                    complete_step,
                    departure_step,
                    "<=",
                    forced=(
                        isinstance(complete_step, int)
                        and isinstance(departure_step, int)
                        and complete_step <= departure_step
                    ),
                ),
            ]
        )
    return _report("alignment_round27_clearance_gate.v1", checks)


def evaluate_stress_gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Reject vacuous stress passes and require typed saturation evidence."""

    scheduled = _integer(metrics, "scheduled_demand_persons")
    opportunities = _integer(metrics, "eligible_service_opportunities")
    completed = _integer(metrics, "completed_persons")
    exhausted = _integer(metrics, "admission_exhausted_attempts")
    waiting = _integer(metrics, "source_waiting_persons")
    active = _integer(metrics, "active_inside_persons")
    not_alighted = _integer(metrics, "not_alighted_persons")
    dropped = _integer(metrics, "dropped_persons")
    outcome = metrics.get("run_outcome_code")
    checks = [
        _check("nonzero_demand", scheduled, 0, ">"),
        _check("nonzero_service_opportunities", opportunities, 0, ">"),
        _check("nonzero_completion", completed, 0, ">"),
        _check("finiteness_exercised", exhausted, 0, ">"),
        _check("dropped_zero", dropped, 0, "=="),
        _check(
            "conserved",
            scheduled,
            waiting + active + completed + not_alighted + dropped,
            "==",
        ),
        _check(
            "structured_outcome",
            outcome,
            "success_or_capacity_failure",
            "==",
            forced=outcome in {None, "train_alighting_capacity_insufficient"},
        ),
        _check(
            "expected_capacity_exception_zero",
            _integer(metrics, "unhandled_expected_capacity_exceptions"),
            0,
            "==",
        ),
    ]
    return _report("alignment_round27_stress_gate.v1", checks)


def _require_sha256(value: str | None, label: str) -> None:
    normalized = str(value or "").lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _require_git_revision(value: str, label: str) -> None:
    normalized = value.lower()
    if len(normalized) != 40 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{label} must be a full Git revision")


def _integer(metrics: Mapping[str, Any], field: str) -> int:
    value = metrics.get(field, 0)
    if isinstance(value, bool):
        return int(value)
    return int(value or 0)


def _check(
    check_id: str,
    actual: Any,
    expected: Any,
    operator: str,
    *,
    forced: bool | None = None,
) -> dict[str, Any]:
    if forced is None:
        if operator == "==":
            passed = actual == expected
        elif operator == ">=":
            passed = actual >= expected
        elif operator == "<=":
            passed = actual <= expected
        elif operator == ">":
            passed = actual > expected
        else:
            raise ValueError(f"unsupported check operator: {operator}")
    else:
        passed = bool(forced)
    return {
        "id": check_id,
        "operator": operator,
        "expected": expected,
        "actual": actual,
        "status": "pass" if passed else "fail",
    }


def _report(
    schema_version: str,
    checks: Sequence[Mapping[str, Any]],
    *,
    floors: Sequence[ThroughputFloor] = (),
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "throughput_floors": [asdict(floor) for floor in floors],
        "checks": list(checks),
    }


__all__ = [
    "ClearanceBottleneckInput",
    "ThroughputFloor",
    "evaluate_clearance_gate",
    "evaluate_dynamic_gate",
    "evaluate_stress_gate",
    "preregister_clearance_prediction",
]
