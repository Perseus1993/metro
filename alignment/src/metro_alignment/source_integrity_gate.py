from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceIntegrityThresholds:
    max_pending_residence_steps_exclusive: int = 10
    max_admission_exhausted_ratio: float = 0.05


DEFAULT_SOURCE_INTEGRITY_THRESHOLDS = SourceIntegrityThresholds()


def evaluate_source_integrity_gate(
    metrics: dict[str, Any],
    *,
    thresholds: SourceIntegrityThresholds = DEFAULT_SOURCE_INTEGRITY_THRESHOLDS,
) -> dict[str, Any]:
    """Evaluate the frozen Round 25 source-integrity tripwire."""

    checks: list[dict[str, Any]] = []

    def equal(check_id: str, field: str, expected: Any) -> None:
        actual = metrics.get(field)
        checks.append(
            {
                "id": check_id,
                "field": field,
                "operator": "==",
                "expected": expected,
                "actual": actual,
                "status": "pass" if actual == expected else "fail",
            }
        )

    for flow in ("entry", "exit"):
        equal(
            f"{flow}_spawned_equals_scheduled",
            f"spawned_{flow}_persons",
            metrics.get(f"alignment_scheduled_{flow}_persons"),
        )
        equal(
            f"{flow}_pending_zero",
            f"alignment_pending_{flow}_persons",
            0,
        )
        equal(
            f"{flow}_pending_groups_zero",
            f"alignment_pending_{flow}_groups",
            0,
        )
        residence_field = f"alignment_{flow}_max_pending_residence_steps"
        residence = metrics.get(residence_field)
        checks.append(
            {
                "id": f"{flow}_pending_residence_bounded",
                "field": residence_field,
                "operator": "<",
                "expected": thresholds.max_pending_residence_steps_exclusive,
                "actual": residence,
                "status": (
                    "pass"
                    if isinstance(residence, (int, float))
                    and residence < thresholds.max_pending_residence_steps_exclusive
                    else "fail"
                ),
            }
        )
        ratio_field = f"alignment_{flow}_admission_exhausted_ratio"
        ratio = metrics.get(ratio_field)
        checks.append(
            {
                "id": f"{flow}_exhaustion_transient",
                "field": ratio_field,
                "operator": "<=",
                "expected": thresholds.max_admission_exhausted_ratio,
                "actual": ratio,
                "status": (
                    "pass"
                    if isinstance(ratio, (int, float))
                    and ratio <= thresholds.max_admission_exhausted_ratio
                    else "fail"
                ),
            }
        )
        equal(
            f"{flow}_dropped_zero",
            f"alignment_{flow}_dropped_persons",
            0,
        )
        equal(
            f"{flow}_conserved",
            f"alignment_{flow}_demand_conserved",
            True,
        )

    equal("source_pending_zero", "alignment_pending_source_persons", 0)
    equal("source_pending_groups_zero", "alignment_pending_source_groups", 0)
    equal("source_dropped_zero", "alignment_source_dropped_persons", 0)
    equal("source_conserved", "alignment_source_demand_conserved", True)
    audit_counts = metrics.get("audit_counts")
    liveness = (
        audit_counts.get("passenger_liveness_violation", 0)
        if isinstance(audit_counts, dict)
        else metrics.get("passenger_liveness_violation", 0)
    )
    checks.append(
        {
            "id": "passenger_liveness_zero",
            "field": "audit_counts.passenger_liveness_violation",
            "operator": "==",
            "expected": 0,
            "actual": liveness,
            "status": "pass" if liveness == 0 else "fail",
        }
    )
    return {
        "schema_version": "alignment_step5_source_integrity_gate.v1",
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "thresholds": asdict(thresholds),
        "checks": checks,
    }


def require_source_integrity_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    report = evaluate_source_integrity_gate(metrics)
    if report["status"] != "pass":
        failures = [
            f"{item['field']}={item['actual']!r} {item['operator']} {item['expected']!r}"
            for item in report["checks"]
            if item["status"] != "pass"
        ]
        raise RuntimeError(
            "alignment source-integrity gate failed; refusing formal evidence: "
            + "; ".join(failures)
        )
    return report


__all__ = [
    "SourceIntegrityThresholds",
    "evaluate_source_integrity_gate",
    "require_source_integrity_gate",
]
