from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from math import hypot

from ..design.schema import QueueSpec
from ..design.validation_issue import ValidationIssue
from ..facilities.process import FacilitySpec
from ..station.facility_portal_binding import Point, QueueSlotBinding


PROJECTION_TOLERANCE_M = 0.02
NUMERICAL_TOLERANCE_M = 1e-6


def topology_fingerprint(slots: tuple[QueueSlotBinding, ...]) -> str:
    payload = json.dumps(
        [asdict(slot) for slot in slots],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def queue_for_facility(
    queues: tuple[QueueSpec, ...],
    facility: FacilitySpec,
) -> QueueSpec | None:
    exact = tuple(
        queue
        for queue in queues
        if queue.level_id == (facility.entry_level_id or queue.level_id)
        and queue.service_direction == facility.direction
    )
    if len(exact) == 1:
        return exact[0]
    legacy = tuple(queue for queue in queues if queue.service_direction is None)
    return legacy[0] if len(legacy) == 1 else None


def queues_by_owner(
    queues: tuple[QueueSpec, ...],
) -> dict[str, tuple[QueueSpec, ...]]:
    grouped: dict[str, list[QueueSpec]] = defaultdict(list)
    for queue in queues:
        grouped[queue.owner_element_id].append(queue)
    return {owner: tuple(items) for owner, items in grouped.items()}


def facade_key(facility: FacilitySpec) -> str:
    return "|".join(
        (
            facility.source_element_id or "",
            facility.stage,
            facility.direction,
            facility.entry_level_id or "",
            facility.exit_level_id or "",
            facility.facility_id,
        )
    )


def point_distance(left: Point, right: Point) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])


def dedupe_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    counts: Counter[tuple[str, str, str, str]] = Counter()
    result: list[ValidationIssue] = []
    for item in issues:
        key = item.severity, item.code, item.path, item.message
        counts[key] += 1
        if counts[key] == 1:
            result.append(item)
    return result


__all__ = [
    "NUMERICAL_TOLERANCE_M",
    "PROJECTION_TOLERANCE_M",
    "dedupe_issues",
    "facade_key",
    "point_distance",
    "queue_for_facility",
    "queues_by_owner",
    "topology_fingerprint",
]
