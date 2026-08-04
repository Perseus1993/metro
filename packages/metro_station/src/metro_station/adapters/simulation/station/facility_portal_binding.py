from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


Point = tuple[float, float]


@dataclass(frozen=True)
class QueueSlotBinding:
    """One immutable standing place and its service-order topology."""

    slot_id: str
    position: Point
    lane_id: str
    row_index: int
    position_in_row: int
    service_rank: int | None
    runtime_slot_index: int | None
    role: str


@dataclass(frozen=True)
class FacilityPortalBinding:
    """Immutable physical facade compiled once for validation and runtime use."""

    facility_id: str
    facade_key: str
    source_element_id: str
    stage: str
    kind: str
    direction: str
    raw_entry_point: Point
    entry_point: Point
    entry_level_id: str
    raw_exit_point: Point
    exit_point: Point
    exit_level_id: str
    release_forward: Point
    release_lateral: Point
    approach_point: Point
    queue_slots: tuple[Point, ...]
    queue_slot_bindings: tuple[QueueSlotBinding, ...]
    approach_slots: tuple[Point, ...]
    approach_source_slot_indices: tuple[int, ...]
    approach_slot_indices: tuple[int, ...]
    queue_id: str | None
    source_queue_capacity: int
    declared_queue_capacity: int
    queue_spacing_m: float
    projection_distance_m: float
    policy_fingerprint: str
    activation_group_id: str | None
    activation_variant_id: str | None
    queue_topology_version: int
    topology_fingerprint: str
    fallback_used: bool = False
    queue_region: Any | None = field(default=None, compare=False, repr=False)


__all__ = ["FacilityPortalBinding", "QueueSlotBinding"]
