from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpatialCapacityEvidence:
    certificate_id: str
    resource_kind: str
    owner_id: str
    certified_body_capacity: int
    current_occupancy_bodies: int
    requested_bodies: int
    passenger_id: int | None


class SpatialCapacityAdmissionError(RuntimeError):
    """Base class for typed runtime capacity/admission outcomes."""

    def __init__(self, message: str, evidence: SpatialCapacityEvidence) -> None:
        super().__init__(message)
        self.evidence = evidence


class SpatialCapacityExhausted(SpatialCapacityAdmissionError):
    """All compiler-certified slots are currently owned."""


class CertifiedPlacementTemporarilyBlocked(SpatialCapacityAdmissionError):
    """A dynamic body temporarily blocks otherwise certified geometry."""


class SpatialCapacityCertificateViolation(SpatialCapacityAdmissionError):
    """Runtime rejected a structurally certified cell without a dynamic owner."""


def record_spatial_capacity_event(
    model: Any,
    code: str,
    evidence: SpatialCapacityEvidence,
) -> None:
    counts = getattr(model, "spatial_capacity_event_counts", None)
    if counts is not None:
        counts[str(code)] += 1
    audit = getattr(model, "audit", None)
    if audit is not None:
        audit.record(
            str(code),
            source="spatial_capacity_admission",
            severity="warning",
            step=int(getattr(model, "step_index", 0)),
            context={
                "certificate_id": evidence.certificate_id,
                "resource_kind": evidence.resource_kind,
                "owner_id": evidence.owner_id,
                "certified_body_capacity": evidence.certified_body_capacity,
                "current_occupancy_bodies": evidence.current_occupancy_bodies,
                "requested_bodies": evidence.requested_bodies,
                "passenger_id": evidence.passenger_id,
            },
        )


__all__ = [
    "CertifiedPlacementTemporarilyBlocked",
    "SpatialCapacityAdmissionError",
    "SpatialCapacityCertificateViolation",
    "SpatialCapacityEvidence",
    "SpatialCapacityExhausted",
    "record_spatial_capacity_event",
]
