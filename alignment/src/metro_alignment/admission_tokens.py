from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite, sqrt
from typing import Any


def required_admission_tokens(
    *,
    count_hour: int,
    residence_seconds: float,
    burst_sigma: float,
) -> int:
    """Size a counting resource from Little's law plus registered headroom."""

    if count_hour < 0:
        raise ValueError("count_hour must be non-negative")
    if not isfinite(residence_seconds) or residence_seconds <= 0.0:
        raise ValueError("residence_seconds must be finite and positive")
    if not isfinite(burst_sigma) or burst_sigma < 0.0:
        raise ValueError("burst_sigma must be finite and non-negative")
    nominal_load = float(count_hour) / 3600.0 * residence_seconds
    return max(1, ceil(nominal_load + burst_sigma * sqrt(nominal_load)))


@dataclass(frozen=True)
class AdmissionTokenPolicy:
    flow_id: str
    count_hour: int
    registered_residence_seconds: float | None
    residence_percentile: str | None
    residence_evidence_ref: str | None
    burst_sigma: float
    configured_capacity: int | None = None
    deterministic_arrival_envelope: int = 0
    evidence_validation_errors: tuple[dict[str, str], ...] = ()

    @property
    def has_registered_residence_evidence(self) -> bool:
        return (
            self.registered_residence_seconds is not None
            and self.residence_percentile in {"p90", "p99"}
            and bool((self.residence_evidence_ref or "").strip())
            and not self.evidence_validation_errors
        )

    @property
    def required_capacity(self) -> int | None:
        if not self.has_registered_residence_evidence:
            return None
        return max(1, int(self.deterministic_arrival_envelope))

    @property
    def effective_capacity(self) -> int | None:
        if self.configured_capacity is not None:
            return int(self.configured_capacity)
        return self.required_capacity

    def preflight(self) -> dict[str, Any]:
        required = self.required_capacity
        capacity = self.effective_capacity
        blockers: list[dict[str, str]] = []
        declared = (
            self.registered_residence_seconds is not None
            and self.residence_percentile in {"p90", "p99"}
            and bool((self.residence_evidence_ref or "").strip())
        )
        if not declared:
            blockers.append(
                {
                    "code": "admission_residence_evidence_missing",
                    "message": (
                        f"{self.flow_id} requires a registered p90 or p99 residence "
                        "measurement before runtime"
                    ),
                }
            )
        blockers.extend(dict(item) for item in self.evidence_validation_errors)
        if required is not None and capacity is not None and capacity < required:
            blockers.append(
                {
                    "code": "admission_capacity_undersized",
                    "message": (
                        f"{self.flow_id} capacity {capacity} is below required {required}"
                    ),
                }
            )
        return {
            "schema_version": "alignment_admission_preflight.v2",
            "flow_id": self.flow_id,
            "status": "pass" if not blockers else "fail",
            "count_hour": self.count_hour,
            "arrival_rate_persons_s": self.count_hour / 3600.0,
            "registered_residence_seconds": self.registered_residence_seconds,
            "residence_percentile": self.residence_percentile,
            "residence_evidence_ref": self.residence_evidence_ref,
            "burst_sigma": self.burst_sigma,
            "deterministic_arrival_envelope": self.deterministic_arrival_envelope,
            "stochastic_reference_capacity": (
                required_admission_tokens(
                    count_hour=self.count_hour,
                    residence_seconds=float(self.registered_residence_seconds),
                    burst_sigma=self.burst_sigma,
                )
                if self.registered_residence_seconds is not None
                else None
            ),
            "sizing_formula": "deterministic maximum arrivals in the registered W window",
            "required_capacity": required,
            "configured_capacity": capacity,
            "resource_semantics": "counting_signal_not_physical_storage",
            "blockers": blockers,
        }


def admission_preflight_report(
    policies: tuple[AdmissionTokenPolicy, ...],
) -> dict[str, Any]:
    flows = [policy.preflight() for policy in policies]
    return {
        "schema_version": "alignment_admission_preflight_bundle.v1",
        "status": "pass" if all(item["status"] == "pass" for item in flows) else "fail",
        "flows": flows,
        "blockers": [
            {"flow_id": item["flow_id"], **blocker}
            for item in flows
            for blocker in item["blockers"]
        ],
    }


def required_entry_admission_tokens(
    *, entry_count_hour: int, residence_seconds: float, burst_sigma: float
) -> int:
    """Compatibility name for callers migrating to the generic policy."""

    return required_admission_tokens(
        count_hour=entry_count_hour,
        residence_seconds=residence_seconds,
        burst_sigma=burst_sigma,
    )


__all__ = [
    "AdmissionTokenPolicy",
    "admission_preflight_report",
    "required_admission_tokens",
    "required_entry_admission_tokens",
]
