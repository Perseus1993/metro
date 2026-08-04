from __future__ import annotations

from dataclasses import replace
from math import nan

from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.design.vertical_landing import (
    design_level_walkable_geometry,
    vertical_landing_position,
)

from .boundary_trial_baseline import boundary_baseline, quality_validation_result


def run_queue_boundary_probe(variant: str) -> tuple[bool, tuple[str, ...]]:
    return quality_validation_result(_queue_design(variant))


def _queue_design(variant: str) -> StationDesignDocument:
    document = boundary_baseline()
    queue = document.queues[0]
    owner = document.element_by_id()[queue.owner_element_id]
    if variant.startswith("SERVICE_"):
        return _queue_service_distance(document, queue, owner, variant)
    if variant == "OWNER_LEVEL_MISMATCH":
        owner_levels = set(owner.connects_levels) | {owner.level_id}
        other_level = next(level.id for level in document.levels if level.id not in owner_levels)
        changed = replace(queue, level_id=other_level)
    elif variant == "UNKNOWN_OWNER":
        changed = replace(queue, owner_element_id="missing_owner")
    elif variant == "OUTSIDE_FOOTPRINT":
        changed = replace(queue, geometry=queue.geometry.moved_to(111.5, 60.0))
    elif variant == "QUEUE_OVERLAP":
        same_level_queue = next(
            item
            for item in document.queues[1:]
            if item.level_id == queue.level_id
        )
        changed = replace(queue, geometry=same_level_queue.geometry)
    elif variant == "QUEUE_BLOCKS_COMPONENT":
        blocker = next(item for item in document.elements if item.id != owner.id and item.kind == "gate")
        changed = replace(queue, geometry=blocker.geometry)
    elif variant == "CAPACITY_ZERO":
        changed = replace(queue, capacity=0)
    elif variant == "CAPACITY_NEGATIVE":
        changed = replace(queue, capacity=-1)
    elif variant == "CAPACITY_HUGE":
        changed = replace(queue, capacity=10**9)
    elif variant == "SPACING_ZERO":
        changed = replace(queue, spacing_m=0.0)
    elif variant == "SPACING_NEGATIVE":
        changed = replace(queue, spacing_m=-1.0)
    else:
        changed = replace(queue, spacing_m=nan)
    return replace(document, queues=(changed, *document.queues[1:]))


def _queue_service_distance(document, queue, owner, variant):
    values = {
        "SERVICE_1_999": (1.999, 0.8),
        "SERVICE_2_000": (2.0, 0.8),
        "SERVICE_2_001": (2.001, 0.8),
        "SERVICE_2_999_SPACING_1_2": (2.999, 1.2),
        "SERVICE_3_000_SPACING_1_2": (3.0, 1.2),
        "SERVICE_3_001_SPACING_1_2": (3.001, 1.2),
    }
    distance, spacing = values[variant]
    landing_x, landing_y = vertical_landing_position(
        owner,
        queue.level_id,
        document.level_by_id(),
        walkable_geometry=design_level_walkable_geometry(document, queue.level_id),
    )
    changed = replace(
        queue,
        service_point_m=(landing_x + distance, landing_y),
        spacing_m=spacing,
    )
    return replace(document, queues=(changed, *document.queues[1:]))
