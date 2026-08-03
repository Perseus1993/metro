from __future__ import annotations

from dataclasses import replace

from metro_station.adapters.simulation.design.schema import (
    DesignElement,
    ElementGeometry,
    QueueSpec,
    StationDesignDocument,
)

from .boundary_trial_baseline import boundary_baseline, design_validation_result


def run_geometry_boundary_probe(group: str, variant: str) -> tuple[bool, tuple[str, ...]]:
    document = _clearance_design(variant) if group == "A" else _footprint_design(variant)
    return design_validation_result(document)


def _clearance_design(variant: str) -> StationDesignDocument:
    document = boundary_baseline()
    level_id = min(document.levels, key=lambda item: item.order).id
    left = DesignElement(
        "boundary_left",
        "obstacle",
        level_id,
        ElementGeometry("rect", x_m=20.0, y_m=60.0, width_m=5.0, height_m=5.0),
        "Boundary left",
    )
    distances = {
        "CLEARANCE_BELOW": 0.499,
        "CLEARANCE_EXACT": 0.5,
        "CLEARANCE_ABOVE": 0.501,
        "CLEARANCE_NOISE_LOW": 0.5 - 1e-9,
    }
    overlaps = {"OVERLAP_BELOW": 0.009, "OVERLAP_EXACT": 0.01, "OVERLAP_ABOVE": 0.011}
    target_x = (
        25.0 + distances[variant]
        if variant in distances
        else 25.0 - overlaps[variant] / 5.0
    )
    right = replace(
        left,
        id="boundary_right",
        label="Boundary right",
        geometry=left.geometry.moved_to(target_x, 60.0),
    )
    return replace(document, elements=(*document.elements, left, right))


def _footprint_design(variant: str) -> StationDesignDocument:
    if variant.startswith("VERTICAL_"):
        return _vertical_footprint_design(variant)
    if variant.startswith("QUEUE_"):
        return _queue_footprint_design(variant)
    document = boundary_baseline()
    shop = next(element for element in document.elements if element.kind == "shop")
    right_edges = {
        "FOOTPRINT_IN": 117.999,
        "FOOTPRINT_EXACT": 118.0,
        "FOOTPRINT_TOL_EXACT": 118.25,
        "FOOTPRINT_TOL_OUT": 118.251,
    }
    geometry = shop.geometry.moved_to(
        right_edges[variant] - shop.geometry.width_m,
        shop.geometry.y_m,
    )
    return replace(
        document,
        elements=tuple(
            replace(item, geometry=geometry) if item.id == shop.id else item
            for item in document.elements
        ),
    )


def _vertical_footprint_design(variant: str) -> StationDesignDocument:
    document = boundary_baseline()
    points = ((2.0, 2.0), (116.0, 2.0), (116.0, 72.0), (2.0, 72.0))
    connector = next(element for element in document.elements if element.kind == "elevator")
    x_m = 116.0 if variant == "VERTICAL_TOUCH" else 116.001
    geometry = ElementGeometry("rect", x_m=x_m, y_m=20.0, width_m=3.0, height_m=3.0)
    return replace(
        document,
        levels=tuple(replace(level, footprint=points) for level in document.levels),
        elements=tuple(
            replace(item, geometry=geometry) if item.id == connector.id else item
            for item in document.elements
        ),
        queues=tuple(item for item in document.queues if item.owner_element_id != connector.id),
    )


def _queue_footprint_design(variant: str) -> StationDesignDocument:
    document = boundary_baseline()
    level_id = min(document.levels, key=lambda item: item.order).id
    owner = DesignElement(
        "boundary_queue_owner",
        "obstacle",
        level_id,
        ElementGeometry("rect", x_m=111.0, y_m=60.0, width_m=5.0, height_m=5.0),
        "Boundary queue owner",
    )
    right = 118.25 if variant == "QUEUE_TOL_EXACT" else 118.251
    queue = QueueSpec(
        "boundary_queue",
        owner.id,
        "lane",
        level_id,
        ElementGeometry("rect", x_m=right - 2.0, y_m=61.0, width_m=2.0, height_m=2.0),
        (116.0, 62.0),
        2,
    )
    return replace(document, elements=(*document.elements, owner), queues=(*document.queues, queue))

