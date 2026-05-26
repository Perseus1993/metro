from __future__ import annotations

from dataclasses import dataclass

try:  # Support both package execution and direct script execution.
    from .specs import FacilityQueueSpec
except ImportError:  # pragma: no cover
    from specs import FacilityQueueSpec


Point = tuple[float, float]


@dataclass(frozen=True)
class RegionPortalSpec:
    """A cross-section that connects one walkable region toward another."""

    label: str
    center: Point
    normal_hint: Point
    width_m: float
    lanes: int
    radius_m: float
    facility: str | None = None


@dataclass(frozen=True)
class RegionFlowPlan:
    """Compiled region-to-capture path before it becomes JuPedSim stages."""

    name: str
    portals: tuple[RegionPortalSpec, ...]
    target_queue_stage_id: int
    target_facility: str


def queue_capture_center(
    queue_spec: FacilityQueueSpec,
    *,
    source: Point,
    capture_aprons: dict[str, tuple[Point, ...]],
) -> Point:
    """Pick the capture apron point facing the source region.

    Queue heads model service order; capture centers model where incoming
    pedestrians can merge into that service order. When a queue has explicit
    apron points, use their centroid weighted toward the source-facing side.
    """

    apron = capture_aprons.get(queue_spec.name)
    if not apron:
        return queue_spec.head

    ranked = sorted(
        apron,
        key=lambda point: (point[0] - source[0]) ** 2 + (point[1] - source[1]) ** 2,
    )
    front = ranked[: max(1, min(3, len(ranked)))]
    return (
        sum(point[0] for point in front) / len(front),
        sum(point[1] for point in front) / len(front),
    )


def build_region_capture_flow(
    *,
    name: str,
    source: Point,
    queue_spec: FacilityQueueSpec,
    queue_stage_id: int,
    capture_aprons: dict[str, tuple[Point, ...]],
    portal_count: int = 2,
    width_m: float = 5.2,
    lanes: int = 4,
    approach_radius_m: float = 2.9,
    capture_radius_m: float = 3.4,
) -> RegionFlowPlan:
    """Compile source region to queue capture band via portal cross-sections."""

    capture = queue_capture_center(
        queue_spec,
        source=source,
        capture_aprons=capture_aprons,
    )
    return build_point_capture_flow(
        name=name,
        source=source,
        capture=capture,
        target_queue_stage_id=queue_stage_id,
        target_facility=queue_spec.name,
        portal_count=portal_count,
        width_m=width_m,
        lanes=lanes,
        approach_radius_m=approach_radius_m,
        capture_radius_m=capture_radius_m,
    )


def build_point_capture_flow(
    *,
    name: str,
    source: Point,
    capture: Point,
    target_queue_stage_id: int,
    target_facility: str,
    portal_count: int = 2,
    width_m: float = 5.2,
    lanes: int = 4,
    approach_radius_m: float = 2.9,
    capture_radius_m: float = 3.4,
) -> RegionFlowPlan:
    """Compile source region to a concrete capture point before a service queue.

    Some JuPedSim queues, such as boarding doors, are generated directly from
    runtime slot geometry instead of a FacilityQueueSpec. This keeps the same
    region-flow semantics without forcing every queue to masquerade as a
    facility spec.
    """

    flow = (capture[0] - source[0], capture[1] - source[1])
    normal = _normal_hint(flow)
    count = max(1, int(portal_count))
    portals: list[RegionPortalSpec] = []
    for index in range(count):
        fraction = (index + 1) / count
        center = (
            source[0] + flow[0] * fraction,
            source[1] + flow[1] * fraction,
        )
        is_capture = index == count - 1
        portals.append(
            RegionPortalSpec(
                label=f"{name}.{'capture' if is_capture else f'portal_{index + 1}'}",
                center=center,
                normal_hint=normal,
                width_m=width_m if not is_capture else max(3.2, width_m * 0.72),
                lanes=lanes if not is_capture else max(2, min(lanes, 3)),
                radius_m=capture_radius_m if is_capture else approach_radius_m,
                facility=target_facility if is_capture else None,
            )
        )
    return RegionFlowPlan(
        name=name,
        portals=tuple(portals),
        target_queue_stage_id=int(target_queue_stage_id),
        target_facility=target_facility,
    )


def _normal_hint(flow: Point) -> Point:
    dx, dy = flow
    if abs(dx) + abs(dy) <= 1e-9:
        return (1.0, 0.0)
    return (-dy, dx)
