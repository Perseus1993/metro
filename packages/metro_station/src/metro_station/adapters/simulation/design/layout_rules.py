from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Point, Polygon

from .geometry import element_shape
from .vertical_landing import (
    design_level_walkable_geometry,
    vertical_landing_position,
)
from .schema import DesignElement, StationDesignDocument


MIN_COMPONENT_CLEARANCE_M = 0.5
FOOTPRINT_TOLERANCE_M = 0.25
OVERLAP_AREA_TOLERANCE_M2 = 0.01


@dataclass(frozen=True)
class ElementSizeLimits:
    min_width_m: float
    max_width_m: float
    min_height_m: float
    max_height_m: float

    def as_dict(self) -> dict[str, float]:
        return {
            "min_width_m": self.min_width_m,
            "max_width_m": self.max_width_m,
            "min_height_m": self.min_height_m,
            "max_height_m": self.max_height_m,
        }


@dataclass(frozen=True)
class LayoutRuleViolation:
    severity: str
    code: str
    path: str
    message: str


ELEMENT_SIZE_LIMITS: dict[str, ElementSizeLimits] = {
    "entrance": ElementSizeLimits(1.0, 12.0, 1.0, 12.0),
    "gate": ElementSizeLimits(4.0, 30.0, 1.5, 10.0),
    "escalator": ElementSizeLimits(2.0, 20.0, 4.0, 30.0),
    "stairs": ElementSizeLimits(3.0, 20.0, 4.0, 30.0),
    "elevator": ElementSizeLimits(3.0, 15.0, 3.0, 15.0),
    "platform_edge": ElementSizeLimits(1.0, 120.0, 0.5, 8.0),
    "shop": ElementSizeLimits(2.0, 50.0, 2.0, 30.0),
    "service_room": ElementSizeLimits(2.0, 50.0, 2.0, 30.0),
    "equipment": ElementSizeLimits(1.0, 40.0, 1.0, 20.0),
    "obstacle": ElementSizeLimits(0.5, 60.0, 0.5, 60.0),
}


def element_size_limits(kind: str) -> ElementSizeLimits | None:
    return ELEMENT_SIZE_LIMITS.get(kind)


def validate_flexible_layout(document: StationDesignDocument) -> list[LayoutRuleViolation]:
    """Validate the minimum safe contract for a draggable, simulatable station layout."""

    issues: list[LayoutRuleViolation] = []
    issues.extend(_validate_minimum_facilities(document))
    issues.extend(_validate_component_sizes(document))
    issues.extend(_validate_footprints(document))
    issues.extend(_validate_component_separation(document))
    issues.extend(_validate_queues(document))
    issues.extend(_validate_vertical_topology(document))
    return issues


def _validate_minimum_facilities(
    document: StationDesignDocument,
) -> list[LayoutRuleViolation]:
    issues: list[LayoutRuleViolation] = []
    elements = document.elements
    requirements = (
        ("entrance", any(element.kind == "entrance" for element in elements), "an entrance"),
        (
            "entry_gate",
            any(
                element.kind == "gate" and element.gate_direction in {"entry", "bidirectional"}
                for element in elements
            ),
            "an entry-capable gate",
        ),
        (
            "exit_gate",
            any(
                element.kind == "gate" and element.gate_direction in {"exit", "bidirectional"}
                for element in elements
            ),
            "an exit-capable gate",
        ),
        (
            "platform_edge",
            any(element.kind == "platform_edge" for element in elements),
            "a platform edge",
        ),
    )
    for code_suffix, present, label in requirements:
        if present:
            continue
        issues.append(
            LayoutRuleViolation(
                "error",
                f"layout.required_{code_suffix}_missing",
                "elements",
                f"A simulatable station layout must contain {label}.",
            )
        )

    floor_levels = {element.level_id for element in elements if element.role == "floor"}
    for level in document.levels:
        if level.id in floor_levels:
            continue
        issues.append(
            LayoutRuleViolation(
                "error",
                "layout.level_floor_missing",
                f"levels.{level.id}",
                f"Level {level.id!r} must contain a floor or walkable zone.",
            )
        )
    return issues


def _validate_component_sizes(document: StationDesignDocument) -> list[LayoutRuleViolation]:
    issues: list[LayoutRuleViolation] = []
    for element in document.elements:
        limits = element_size_limits(element.kind)
        if limits is None or element.geometry.shape != "rect" or element.role == "floor":
            continue
        width = element.geometry.width_m
        height = element.geometry.height_m
        if not limits.min_width_m <= width <= limits.max_width_m:
            issues.append(
                LayoutRuleViolation(
                    "error",
                    "layout.component_width_out_of_range",
                    f"elements.{element.id}.geometry.width_m",
                    f"{element.id} width {width:g}m must be between "
                    f"{limits.min_width_m:g}m and {limits.max_width_m:g}m.",
                )
            )
        if not limits.min_height_m <= height <= limits.max_height_m:
            issues.append(
                LayoutRuleViolation(
                    "error",
                    "layout.component_height_out_of_range",
                    f"elements.{element.id}.geometry.height_m",
                    f"{element.id} height {height:g}m must be between "
                    f"{limits.min_height_m:g}m and {limits.max_height_m:g}m.",
                )
            )
    return issues


def _validate_footprints(document: StationDesignDocument) -> list[LayoutRuleViolation]:
    issues: list[LayoutRuleViolation] = []
    footprints = {
        level.id: Polygon(level.footprint) for level in document.levels if len(level.footprint) >= 3
    }
    for element in document.elements:
        if element.role == "floor" or element.level_id not in footprints:
            continue
        shape = element_shape(element.geometry)
        if element.role == "vertical_connector":
            for level_id in element.connects_levels:
                footprint = footprints.get(level_id)
                if footprint is None or shape.intersects(footprint):
                    continue
                issues.append(
                    LayoutRuleViolation(
                        "error",
                        "layout.vertical_connector_misses_level",
                        f"elements.{element.id}.geometry",
                        f"{element.id} does not intersect connected level {level_id!r}.",
                    )
                )
            continue

        footprint = footprints[element.level_id].buffer(FOOTPRINT_TOLERANCE_M)
        if footprint.covers(shape):
            continue
        issues.append(
            LayoutRuleViolation(
                "error",
                "layout.component_outside_level_footprint",
                f"elements.{element.id}.geometry",
                f"{element.id} must remain inside the {element.level_id!r} level footprint.",
            )
        )
    return issues


def _validate_component_separation(
    document: StationDesignDocument,
) -> list[LayoutRuleViolation]:
    issues: list[LayoutRuleViolation] = []
    elements = [element for element in document.elements if _is_independent_component(element)]
    for index, left in enumerate(elements):
        left_shape = element_shape(left.geometry)
        for right in elements[index + 1 :]:
            if left.level_id != right.level_id or _is_fare_barrier_pair(left, right):
                continue
            right_shape = element_shape(right.geometry)
            overlap_area = left_shape.intersection(right_shape).area
            if overlap_area > OVERLAP_AREA_TOLERANCE_M2:
                issues.append(
                    LayoutRuleViolation(
                        "error",
                        "layout.components_overlap",
                        f"elements.{left.id}",
                        f"{left.id} overlaps {right.id}; move the components apart.",
                    )
                )
                continue
            distance = left_shape.distance(right_shape)
            if distance + 1e-9 >= MIN_COMPONENT_CLEARANCE_M:
                continue
            issues.append(
                LayoutRuleViolation(
                    "error",
                    "layout.component_clearance_too_small",
                    f"elements.{left.id}",
                    f"{left.id} and {right.id} need at least "
                    f"{MIN_COMPONENT_CLEARANCE_M:g}m clearance (actual {distance:.2f}m).",
                )
            )
    return issues


def _validate_queues(document: StationDesignDocument) -> list[LayoutRuleViolation]:
    issues: list[LayoutRuleViolation] = []
    elements_by_id = document.element_by_id()
    footprints = {
        level.id: Polygon(level.footprint).buffer(FOOTPRINT_TOLERANCE_M)
        for level in document.levels
        if len(level.footprint) >= 3
    }
    for queue in document.queues:
        owner = elements_by_id.get(queue.owner_element_id)
        if owner is None:
            continue
        valid_owner_levels = (
            set(owner.connects_levels)
            if owner.role == "vertical_connector"
            else {owner.level_id}
        )
        if queue.level_id not in valid_owner_levels:
            issues.append(
                LayoutRuleViolation(
                    "error",
                    "layout.queue_owner_level_mismatch",
                    f"queues.{queue.id}.level_id",
                    f"{queue.id} must use a landing level served by owner {owner.id}.",
                )
            )
        footprint = footprints.get(queue.level_id)
        if footprint is not None and not footprint.covers(element_shape(queue.geometry)):
            issues.append(
                LayoutRuleViolation(
                    "error",
                    "layout.queue_outside_level_footprint",
                    f"queues.{queue.id}.geometry",
                    f"{queue.id} must remain inside the {queue.level_id!r} level footprint.",
                )
            )
        if owner.role == "vertical_connector" and queue.level_id in owner.connects_levels:
            expected_landing = vertical_landing_position(
                owner,
                queue.level_id,
                document.level_by_id(),
                walkable_geometry=design_level_walkable_geometry(
                    document,
                    queue.level_id,
                ),
            )
            service_distance = Point(queue.service_point_m).distance(Point(expected_landing))
            maximum_service_distance = max(2.0, queue.spacing_m * 2.5)
        else:
            service_distance = Point(queue.service_point_m).distance(
                element_shape(owner.geometry)
            )
            maximum_service_distance = max(2.0, queue.spacing_m * 2.5)
        if service_distance <= maximum_service_distance:
            continue
        issues.append(
            LayoutRuleViolation(
                "error",
                "layout.queue_service_point_detached",
                f"queues.{queue.id}.service_point_m",
                f"{queue.id} service point is {service_distance:.2f}m from owner {owner.id}.",
            )
        )
    return issues


def _validate_vertical_topology(
    document: StationDesignDocument,
) -> list[LayoutRuleViolation]:
    if len(document.levels) <= 1:
        return []
    connectors = [element for element in document.elements if element.role == "vertical_connector"]
    if not connectors:
        return [
            LayoutRuleViolation(
                "error",
                "layout.vertical_connector_required",
                "elements",
                "A multi-level station must contain a vertical connector.",
            )
        ]

    participating_levels = {
        element.level_id
        for element in document.elements
        if element.kind in {"entrance", "gate", "platform_edge"}
    }
    connected_levels = {
        level_id for connector in connectors for level_id in connector.connects_levels
    }
    issues: list[LayoutRuleViolation] = []
    for level_id in sorted(participating_levels - connected_levels):
        issues.append(
            LayoutRuleViolation(
                "error",
                "layout.participating_level_not_connected",
                f"levels.{level_id}",
                f"Level {level_id!r} contains journey facilities but no vertical connector.",
            )
        )
    return issues


def _is_independent_component(element: DesignElement) -> bool:
    if element.role == "floor" or element.kind == "walkable_area":
        return False
    if element.kind == "obstacle" and not bool(element.metadata.get("blocking", True)):
        return False
    return True


def _is_fare_barrier_pair(left: DesignElement, right: DesignElement) -> bool:
    pair = (left, right)
    return any(element.kind == "gate" for element in pair) and any(
        element.kind == "obstacle" and element.metadata.get("visual_kind") == "fare_barrier"
        for element in pair
    )
