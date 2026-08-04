from __future__ import annotations

from collections.abc import Iterable

import jupedsim as jps
from shapely.geometry import Point, Polygon

from ..queue_runtime import (
    NativeQueueRuntime,
    QUEUE_CAPTURE_APRONS_N,
    facility_queue_extra_positions_n,
    normalized_from_meters,
)
from .constants import (
    ENTRY_GATE_CANDIDATES,
    ENTRY_GATE_PORTAL_RADIUS_M,
    POST_GATE_RADIUS_M,
)
from .types import StageInfo, StageRegistry


def exit_box(center: tuple[float, float], half_size: float = 0.8) -> Polygon:
    x, y = center
    return Polygon(
        [
            (x - half_size, y - half_size),
            (x + half_size, y - half_size),
            (x + half_size, y + half_size),
            (x - half_size, y + half_size),
        ]
    )


def meter_point(point: tuple[float, float]) -> tuple[float, float]:
    return float(point[0]), float(point[1])


def register_stage(
    stage_registry: StageRegistry,
    stage_id: int,
    *,
    kind: str,
    label: str,
    point_m: tuple[float, float] | None = None,
    radius_m: float | None = None,
    slots_m: Iterable[tuple[float, float]] = (),
    facility: str | None = None,
    journey: str | None = None,
) -> int:
    slots = tuple(meter_point(point) for point in slots_m)
    stage_registry[int(stage_id)] = StageInfo(
        stage_id=int(stage_id),
        kind=kind,
        label=label,
        point_m=meter_point(point_m) if point_m is not None else (slots[0] if slots else None),
        radius_m=float(radius_m) if radius_m is not None else None,
        slots_m=slots,
        facility=facility,
        journey=journey,
    )
    return int(stage_id)


def add_registered_waypoint_stage(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    label: str,
    point_m: tuple[float, float],
    radius_m: float,
    *,
    facility: str | None = None,
    journey: str | None = None,
) -> int:
    stage_id = sim.add_waypoint_stage(point_m, radius_m)
    return register_stage(
        stage_registry,
        stage_id,
        kind="waypoint",
        label=label,
        point_m=point_m,
        radius_m=radius_m,
        facility=facility,
        journey=journey,
    )


def add_registered_exit_stage(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    label: str,
    center_m: tuple[float, float],
    half_size_m: float,
    *,
    facility: str | None = None,
    journey: str | None = None,
) -> int:
    stage_id = sim.add_exit_stage(exit_box(center_m, half_size_m))
    return register_stage(
        stage_registry,
        stage_id,
        kind="exit",
        label=label,
        point_m=center_m,
        radius_m=half_size_m,
        facility=facility,
        journey=journey,
    )


def add_registered_queue_stage(
    sim: jps.Simulation,
    stage_registry: StageRegistry,
    label: str,
    positions_m: list[tuple[float, float]],
    *,
    facility: str,
    journey: str | None = None,
) -> int:
    stage_id = sim.add_queue_stage(positions_m)
    return register_stage(
        stage_registry,
        stage_id,
        kind="queue",
        label=label,
        slots_m=positions_m,
        facility=facility,
        journey=journey,
    )


def geometry_components(geometry: Polygon) -> list[Polygon]:
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [
        part
        for part in getattr(geometry, "geoms", [])
        if getattr(part, "geom_type", None) == "Polygon"
    ]


def component_index(components: list[Polygon], point_m: tuple[float, float]) -> int | None:
    point = Point(point_m)
    for index, component in enumerate(components):
        if component.covers(point):
            return index
    return None


def stage_info_payload(info: StageInfo) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": info.stage_id,
        "kind": info.kind,
        "label": info.label,
    }
    if info.facility is not None:
        payload["facility"] = info.facility
    if info.journey is not None:
        payload["journey"] = info.journey
    if info.point_m is not None:
        payload["point"] = normalized_from_meters(info.point_m)
        payload["point_m"] = [round(info.point_m[0], 3), round(info.point_m[1], 3)]
    if info.radius_m is not None:
        payload["radius_m"] = round(info.radius_m, 3)
    if info.slots_m:
        payload["slot_count"] = len(info.slots_m)
        payload["head"] = normalized_from_meters(info.slots_m[0])
        payload["tail"] = normalized_from_meters(info.slots_m[-1])
        payload["slots"] = [normalized_from_meters(point) for point in info.slots_m]
    return payload


def stage_registry_payload(stage_registry: StageRegistry) -> list[dict[str, object]]:
    return [
        stage_info_payload(info)
        for info in sorted(stage_registry.values(), key=lambda item: item.stage_id)
    ]


def build_stage_geometry_diagnostics(
    stage_registry: StageRegistry,
    geometry: Polygon,
) -> dict[str, object]:
    components = geometry_components(geometry)
    outside_refs: list[dict[str, object]] = []
    multi_component_stages: list[dict[str, object]] = []
    queue_stages: list[StageInfo] = []
    decision_stages: list[dict[str, object]] = []

    for info in sorted(stage_registry.values(), key=lambda item: item.stage_id):
        refs: list[tuple[str, int | None, tuple[float, float]]] = []
        if info.point_m is not None:
            refs.append(("point", None, info.point_m))
        refs.extend(("slot", index, point) for index, point in enumerate(info.slots_m))

        component_ids: list[int] = []
        stage_outside: list[dict[str, object]] = []
        for ref_kind, ref_index, point in refs:
            point_component = component_index(components, point)
            if point_component is None:
                stage_outside.append(
                    {
                        "ref": ref_kind,
                        "index": ref_index,
                        "point": normalized_from_meters(point),
                    }
                )
            else:
                component_ids.append(point_component)

        if stage_outside:
            outside_refs.append(
                {
                    "stage_id": info.stage_id,
                    "label": info.label,
                    "kind": info.kind,
                    "outside_count": len(stage_outside),
                    "refs": stage_outside[:8],
                }
            )

        unique_components = sorted(set(component_ids))
        if len(unique_components) > 1:
            multi_component_stages.append(
                {
                    "stage_id": info.stage_id,
                    "label": info.label,
                    "kind": info.kind,
                    "components": unique_components,
                }
            )

        if info.kind == "queue":
            queue_stages.append(info)
        if info.kind == "waypoint" and info.radius_m is not None and info.radius_m >= 2.0:
            decision_stages.append(
                {
                    "stage_id": info.stage_id,
                    "label": info.label,
                    "radius_m": round(info.radius_m, 3),
                    "point": normalized_from_meters(info.point_m)
                    if info.point_m is not None
                    else None,
                }
            )

    return {
        "component_count": len(components),
        "stage_count": len(stage_registry),
        "queue_stage_count": len(queue_stages),
        "outside_stage_count": len(outside_refs),
        "outside_stage_refs": outside_refs[:80],
        "multi_component_stage_count": len(multi_component_stages),
        "multi_component_stages": multi_component_stages[:80],
        "decision_stage_count": len(decision_stages),
        "decision_radii": decision_stages,
    }


def entry_gate_runtimes_for_side(
    side: str,
    lane: int,
    gate_runtimes: list[NativeQueueRuntime],
) -> list[NativeQueueRuntime]:
    """Keep gate choice inside the physically reachable gate bank."""

    candidate_indices = ENTRY_GATE_CANDIDATES.get((side, lane))
    if candidate_indices is None:
        return gate_runtimes
    return [gate_runtimes[index] for index in candidate_indices if 0 <= index < len(gate_runtimes)]


def right_entry_paid_corridor_center(
    gate_runtimes: list[NativeQueueRuntime],
    downstream_center: tuple[float, float],
) -> tuple[float, float]:
    exits = [runtime.spec.exit for runtime in gate_runtimes if runtime.spec is not None]
    if not exits:
        return downstream_center
    gate_center = (
        sum(point[0] for point in exits) / len(exits),
        sum(point[1] for point in exits) / len(exits),
    )
    return (
        (gate_center[0] + downstream_center[0]) / 2.0,
        (gate_center[1] + downstream_center[1]) / 2.0,
    )


def post_gate_portal_radius(runtime: NativeQueueRuntime) -> float:
    if runtime.spec is not None and runtime.spec.name.startswith("entry_gate"):
        return ENTRY_GATE_PORTAL_RADIUS_M
    return POST_GATE_RADIUS_M


def native_queue_capture_aprons_n(
    runtimes: Iterable[NativeQueueRuntime],
) -> dict[str, tuple[tuple[float, float], ...]]:
    aprons: dict[str, tuple[tuple[float, float], ...]] = dict(QUEUE_CAPTURE_APRONS_N)
    for runtime in runtimes:
        if runtime.spec is None:
            continue
        extra = facility_queue_extra_positions_n(runtime.spec)
        if extra:
            aprons[runtime.spec.name] = extra
    return aprons
