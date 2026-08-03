"""Framework-independent contracts for reproducible analysis cases."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .fingerprinting import analysis_case_fingerprint
from .validation import validate_seeds, validate_simulation


ANALYSIS_CASE_SCHEMA_VERSION = "analysis-case/v1"
EVIDENCE_STATUS_SCHEMA_VERSION = "evidence-status/v1"
CALIBRATION_STATUSES = frozenset({"uncalibrated", "calibrated", "validated"})
DEFAULT_SAFE_USE_BOUNDARY = (
    "Internal exploration only; not approved for production operations, capacity commitments, "
    "evacuation certification, or fire-safety decisions."
)


@dataclass(frozen=True)
class EvidenceStatus:
    calibration_profile_id: str = "default_uncalibrated"
    calibration_status: str = "uncalibrated"
    product_version: str = "0.1.0"
    model_version: str = "mesa-jupedsim-default"
    safe_use_boundary: str = DEFAULT_SAFE_USE_BOUNDARY
    notes: str = "Default parameters have not been independently calibrated or validated."
    limitations: tuple[str, ...] = (
        "model_not_independently_validated",
        "safety_density_threshold_not_approved",
    )
    schema_version: str = EVIDENCE_STATUS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_STATUS_SCHEMA_VERSION:
            raise ValueError(f"unsupported evidence schema: {self.schema_version!r}")
        if self.calibration_status not in CALIBRATION_STATUSES:
            raise ValueError(f"unsupported calibration status: {self.calibration_status!r}")
        for name, value in (
            ("calibration_profile_id", self.calibration_profile_id),
            ("product_version", self.product_version),
            ("model_version", self.model_version),
            ("safe_use_boundary", self.safe_use_boundary),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} must not be blank")

    @property
    def research_ready(self) -> bool:
        return self.calibration_status == "validated"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "calibration_profile_id": self.calibration_profile_id,
            "calibration_status": self.calibration_status,
            "research_ready": self.research_ready,
            "product_version": self.product_version,
            "model_version": self.model_version,
            "safe_use_boundary": self.safe_use_boundary,
            "notes": self.notes,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvidenceStatus:
        values = dict(payload)
        claimed_ready = values.pop("research_ready", None)
        values["limitations"] = tuple(values.get("limitations", ()))
        status = cls(**values)
        if claimed_ready is not None and bool(claimed_ready) != status.research_ready:
            raise ValueError("research_ready contradicts calibration_status")
        return status


@dataclass(frozen=True)
class AnalysisCase:
    case_id: str
    name: str
    design: dict[str, Any]
    operations: dict[str, int | float]
    simulation: dict[str, Any]
    seeds: tuple[int, ...]
    evidence: EvidenceStatus = field(default_factory=EvidenceStatus)
    revision: int = 1
    parent_case_id: str | None = None
    created_at: str = field(default_factory=lambda: _timestamp())
    updated_at: str = field(default_factory=lambda: _timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = ANALYSIS_CASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ANALYSIS_CASE_SCHEMA_VERSION:
            raise ValueError(f"unsupported analysis-case schema: {self.schema_version!r}")
        if not self.case_id.strip() or not self.name.strip():
            raise ValueError("case_id and name must not be blank")
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        validate_seeds(self.seeds)
        validate_simulation(self.simulation)
        if not isinstance(self.design, dict) or not isinstance(self.operations, dict):
            raise ValueError("design and operations must be objects")

    @property
    def semantic_fingerprint(self) -> str:
        return analysis_case_fingerprint(self)

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "design": deepcopy(self.design),
            "operations": dict(sorted(self.operations.items())),
            "simulation": deepcopy(self.simulation),
            "seeds": list(self.seeds),
            "evidence": self.evidence.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "name": self.name,
            "revision": self.revision,
            "parent_case_id": self.parent_case_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "semantic_fingerprint": self.semantic_fingerprint,
            **self.semantic_payload(),
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> AnalysisCase:
        values = dict(payload)
        expected_fingerprint = values.pop("semantic_fingerprint", None)
        values["design"] = deepcopy(values.get("design", {}))
        values["operations"] = dict(values.get("operations", {}))
        values["simulation"] = deepcopy(values.get("simulation", {}))
        values["metadata"] = deepcopy(values.get("metadata", {}))
        values["seeds"] = tuple(int(seed) for seed in values.get("seeds", ()))
        evidence = values.get("evidence", {})
        values["evidence"] = EvidenceStatus.from_dict(evidence)
        case = cls(**values)
        if expected_fingerprint and expected_fingerprint != case.semantic_fingerprint:
            raise ValueError("analysis-case semantic fingerprint mismatch")
        return case


def create_analysis_case(
    *,
    name: str,
    design: Mapping[str, Any],
    operations: Mapping[str, int | float],
    simulation: Mapping[str, Any],
    seeds: tuple[int, ...] = (42,),
    evidence: EvidenceStatus | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AnalysisCase:
    return AnalysisCase(
        case_id=uuid4().hex,
        name=name,
        design=deepcopy(dict(design)),
        operations=dict(operations),
        simulation=deepcopy(dict(simulation)),
        seeds=tuple(seeds),
        evidence=evidence or EvidenceStatus(),
        metadata=deepcopy(dict(metadata or {})),
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
