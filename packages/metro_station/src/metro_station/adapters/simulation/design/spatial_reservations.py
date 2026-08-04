from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .geometry import element_shape
from .schema import QueueSpec, StationDesignDocument


@dataclass(frozen=True)
class SpatialReservation:
    """One design-time claim on a level's finite physical area."""

    owner_id: str
    resource_kind: str
    shape: Any


def level_spatial_reservations(
    document: StationDesignDocument,
    queues: Iterable[QueueSpec],
) -> dict[str, list[SpatialReservation]]:
    reservations: dict[str, list[SpatialReservation]] = {
        level.id: [] for level in document.levels
    }
    for element in document.elements:
        if element.role == "floor":
            continue
        if element.kind == "obstacle" and not element.metadata.get("blocking", True):
            continue
        level_ids = (
            element.connects_levels
            if element.role == "vertical_connector"
            else (element.level_id,)
        )
        for level_id in level_ids:
            reservations.setdefault(level_id, []).append(
                SpatialReservation(
                    owner_id=element.id,
                    resource_kind="facility_or_obstacle",
                    shape=element_shape(element.geometry),
                )
            )
    for queue in queues:
        reservations.setdefault(queue.level_id, []).append(queue_reservation(queue))
    return reservations


def queue_reservation(queue: QueueSpec) -> SpatialReservation:
    return SpatialReservation(
        owner_id=queue.id,
        resource_kind="queue",
        shape=element_shape(queue.geometry),
    )


def conflicting_area(
    candidate_shape: Any,
    reservations: Iterable[SpatialReservation],
    *,
    facility_owner_id: str,
) -> float:
    """Return overlap with resources that may coexist with this queue.

    A queue is allowed to meet/overlap its own mechanical facade at the
    handoff boundary.  It may not overlap another facility, obstacle, or a
    second queue owned by another directional facade of the same facility.
    """

    return sum(
        candidate_shape.intersection(reservation.shape).area
        for reservation in reservations
        if not (
            reservation.resource_kind == "facility_or_obstacle"
            and reservation.owner_id == facility_owner_id
        )
    )


__all__ = [
    "SpatialReservation",
    "conflicting_area",
    "level_spatial_reservations",
    "queue_reservation",
]
