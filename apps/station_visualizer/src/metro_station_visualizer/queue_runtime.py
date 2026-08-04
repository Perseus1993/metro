from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import jupedsim as jps
from shapely.geometry import LineString, Point, Polygon

try:  # Support both package execution and direct script execution.
    from .config import H, PX_PER_METER, W
    from .geometry import canvas, meters, px
    from .layout import STATION_LAYOUT
    from .process_model import PROCESS_MODEL
    from .specs import FacilityQueueSpec, NATIVE_QUEUE_TAIL_VECTORS
except ImportError:  # pragma: no cover
    from config import H, PX_PER_METER, W
    from geometry import canvas, meters, px
    from layout import STATION_LAYOUT
    from process_model import PROCESS_MODEL
    from specs import FacilityQueueSpec, NATIVE_QUEUE_TAIL_VECTORS


BOARDING_QUEUE_HEAD_Y = 0.735
BOARDING_SCREEN_DOOR_Y = 0.765
BOARDING_VESTIBULE_Y = 0.807
BOARDING_EXIT_Y = 0.842

QUEUE_CAPTURE_APRONS_N: dict[str, tuple[tuple[float, float], ...]] = {
    "down_escalator_1_queue": (
        (0.238, 0.407),
        (0.256, 0.401),
        (0.274, 0.395),
        (0.292, 0.389),
        (0.314, 0.392),
        (0.336, 0.394),
    ),
    "down_escalator_2_queue": (
        (0.548, 0.402),
        (0.565, 0.395),
        (0.582, 0.388),
        (0.599, 0.381),
    ),
    "up_escalator_1_queue": (
        (0.272, 0.744),
        (0.260, 0.758),
        (0.248, 0.772),
        (0.236, 0.786),
    ),
    "up_escalator_2_queue": (
        (0.790, 0.736),
        (0.778, 0.750),
        (0.766, 0.764),
        (0.754, 0.778),
    ),
}


@dataclass
class NativeQueueRuntime:
    name: str
    source: str
    color: str
    stage_id: int
    service_interval: float
    next_service: float
    batch_size: int = 1
    spec: FacilityQueueSpec | None = None
    train_service: bool = False
    positions_m: tuple[tuple[float, float], ...] = ()
    virtual_queue_order: dict[int, int] = field(default_factory=dict)
    next_virtual_queue_order: int = 0


@dataclass(frozen=True)
class QueueVisualAssignment:
    runtime: NativeQueueRuntime
    order: int
    total_count: int
    mode: str


def pixels_to_meters(point: tuple[float, float]) -> tuple[float, float]:
    return point[0] / PX_PER_METER, point[1] / PX_PER_METER


def normalized_from_pixels(point: tuple[float, float]) -> list[float]:
    return [round(point[0] / W, 5), round(point[1] / H, 5)]


def normalized_from_meters(point: tuple[float, float]) -> list[float]:
    return normalized_from_pixels(canvas(point))


def queue_slot_position_px(spec: FacilityQueueSpec, slot: int) -> tuple[float, float]:
    lane = slot % spec.lanes
    row = slot // spec.lanes
    lane_offset = (lane - (spec.lanes - 1) / 2.0) * 0.011
    head = px(spec.head)
    tail_vector = NATIVE_QUEUE_TAIL_VECTORS.get(spec.name, spec.tail_vector)
    tail = (tail_vector[0] * W, tail_vector[1] * H)
    normal = (-tail[1], tail[0])
    normal_len = max(1.0, math.hypot(normal[0], normal[1]))
    tail_len = max(1.0, math.hypot(tail[0], tail[1]))
    jitter_x, jitter_y = queue_slot_jitter_px(spec, slot, normal, normal_len, tail, tail_len)
    return (
        head[0] + tail[0] * row + normal[0] / normal_len * lane_offset * W + jitter_x,
        head[1] + tail[1] * row + normal[1] / normal_len * lane_offset * H + jitter_y,
    )


def queue_slot_jitter_px(
    spec: FacilityQueueSpec,
    slot: int,
    normal: tuple[float, float],
    normal_len: float,
    tail: tuple[float, float],
    tail_len: float,
) -> tuple[float, float]:
    if slot == 0:
        return 0.0, 0.0
    lateral = (stable_noise(f"{spec.name}:{slot}:lateral") - 0.5) * 4.6
    longitudinal = (stable_noise(f"{spec.name}:{slot}:longitudinal") - 0.5) * 2.4
    if spec.name.startswith("entry_gate"):
        lateral *= 0.72
        longitudinal *= 0.65
    elif spec.name.startswith("exit_gate"):
        lateral *= 0.68
        longitudinal *= 0.60
    return (
        normal[0] / normal_len * lateral + tail[0] / tail_len * longitudinal,
        normal[1] / normal_len * lateral + tail[1] / tail_len * longitudinal,
    )


def stable_noise(key: str) -> float:
    total = sum((index + 1) * ord(char) for index, char in enumerate(key))
    return math.sin(total * 12.9898) * 43758.5453 % 1.0


def queue_visual_assignments(
    sim: jps.Simulation,
    runtimes: Iterable[NativeQueueRuntime],
) -> dict[int, QueueVisualAssignment]:
    assignments: dict[int, QueueVisualAssignment] = {}
    runtime_list = list(runtimes)
    runtime_by_stage = {runtime.stage_id: runtime for runtime in runtime_list}
    queued_counts: dict[int, int] = {}
    for runtime in runtime_list:
        stage = sim.get_stage(runtime.stage_id)
        queued = [int(agent_id) for agent_id in stage.enqueued()]
        queued_count = len(queued)
        queued_counts[runtime.stage_id] = queued_count
        for order, sim_id in enumerate(queued):
            assignments[sim_id] = QueueVisualAssignment(
                runtime=runtime,
                order=order,
                total_count=queued_count,
                mode="enqueued",
            )

    targeting: dict[int, list[tuple[float, int]]] = {
        runtime.stage_id: [] for runtime in runtime_list
    }
    for agent in sim.agents():
        sim_id = int(agent.id)
        if sim_id in assignments:
            continue
        stage_id = int(agent.stage_id)
        runtime = runtime_by_stage.get(stage_id)
        if runtime is None:
            continue
        position = (float(agent.position[0]), float(agent.position[1]))
        distance = queue_service_distance_m(runtime, position)
        if distance > queue_visual_capture_radius_m(runtime):
            continue
        targeting[stage_id].append((distance, sim_id))

    for stage_id, candidates in targeting.items():
        runtime = runtime_by_stage[stage_id]
        queued_count = queued_counts.get(stage_id, 0)
        candidates.sort()
        total_count = queued_count + len(candidates)
        for index, (_distance, sim_id) in enumerate(candidates):
            assignments[sim_id] = QueueVisualAssignment(
                runtime=runtime,
                order=queued_count + index,
                total_count=total_count,
                mode="targeting",
            )
    return assignments


def queue_visual_capture_radius_m(runtime: NativeQueueRuntime) -> float:
    if runtime.spec is not None and runtime.spec.name.startswith("entry_gate"):
        return 4.0
    if runtime.spec is not None and runtime.spec.name.startswith("exit_gate"):
        return 1.20
    if runtime.spec is not None and "escalator" in runtime.spec.name:
        return 1.25
    if runtime.spec is not None and "elevator" in runtime.spec.name:
        return 1.35
    if runtime.spec is not None and runtime.spec.name.startswith("stairs"):
        return 1.20
    if runtime.spec is None and runtime.name.startswith("boarding"):
        return 1.45
    return 1.20


def queue_service_slots_m(runtime: NativeQueueRuntime) -> list[tuple[float, float]]:
    if runtime.positions_m:
        return list(runtime.positions_m)
    if runtime.spec is not None:
        slot_count = max(runtime.spec.slots, runtime.spec.lanes * 5)
        return [
            pixels_to_meters(queue_slot_position_px(runtime.spec, slot))
            for slot in range(slot_count)
        ]

    match = re.match(r"boarding_door_(\d+)", runtime.name)
    door_index = int(match.group(1)) - 1 if match else 0
    door_index = max(0, min(door_index, len(STATION_LAYOUT.control_points["platform_doors"]) - 1))
    door_x = float(STATION_LAYOUT.control_points["platform_doors"][door_index][0])
    positions: list[tuple[float, float]] = []
    for row in range(10):
        for lane in range(2):
            lateral = (-0.012 if lane == 0 else 0.012) + (0.003 if row % 2 else -0.003)
            positions.append(meters((door_x + lateral, BOARDING_QUEUE_HEAD_Y - row * 0.014)))
    return positions


def queue_service_distance_m(runtime: NativeQueueRuntime, position: tuple[float, float]) -> float:
    return min(
        math.hypot(position[0] - slot[0], position[1] - slot[1])
        for slot in queue_service_slots_m(runtime)
    )


def queue_assignment_target_px(assignment: QueueVisualAssignment) -> tuple[float, float]:
    runtime = assignment.runtime
    if assignment.mode == "targeting":
        if runtime.spec is not None:
            return px(runtime.spec.head)
        match = re.match(r"boarding_door_(\d+)", runtime.name)
        door_index = int(match.group(1)) - 1 if match else 0
        door_index = max(
            0, min(door_index, len(STATION_LAYOUT.control_points["platform_doors"]) - 1)
        )
        door_x = float(STATION_LAYOUT.control_points["platform_doors"][door_index][0])
        return px((door_x, BOARDING_QUEUE_HEAD_Y))

    if runtime.spec is not None:
        slot = min(max(assignment.order, 0), max(runtime.spec.slots - 1, 0))
        return queue_slot_position_px(runtime.spec, slot)

    match = re.match(r"boarding_door_(\d+)", runtime.name)
    door_index = int(match.group(1)) - 1 if match else 0
    door_index = max(0, min(door_index, len(STATION_LAYOUT.control_points["platform_doors"]) - 1))
    door_x = float(STATION_LAYOUT.control_points["platform_doors"][door_index][0])
    row = min(max(assignment.order // 2, 0), 9)
    lane = assignment.order % 2
    lateral = -0.012 if lane == 0 else 0.012
    return px((door_x + lateral, BOARDING_QUEUE_HEAD_Y - row * 0.014))


def queue_assignment_slot_px(assignment: QueueVisualAssignment) -> tuple[float, float]:
    runtime = assignment.runtime
    if runtime.spec is not None:
        slot = min(
            max(assignment.order, 0),
            max(runtime.spec.slots - 1, 0),
        )
        return queue_slot_position_px(runtime.spec, slot)

    match = re.match(r"boarding_door_(\d+)", runtime.name)
    door_index = int(match.group(1)) - 1 if match else 0
    door_index = max(0, min(door_index, len(STATION_LAYOUT.control_points["platform_doors"]) - 1))
    door_x = float(STATION_LAYOUT.control_points["platform_doors"][door_index][0])
    row = min(max(assignment.order // 2, 0), 9)
    lane = assignment.order % 2
    lateral = -0.012 if lane == 0 else 0.012
    return px((door_x + lateral, BOARDING_QUEUE_HEAD_Y - row * 0.014))


def queue_render_position_m(
    assignment: QueueVisualAssignment,
    current_position_m: tuple[float, float],
    geometry: Polygon,
) -> tuple[float, float]:
    slot_px = queue_assignment_slot_px(assignment)
    slot_m = pixels_to_meters(slot_px)
    if not geometry.covers(LineString([current_position_m, slot_m])):
        return current_position_m
    blend = 0.92 if assignment.mode == "enqueued" else 0.62
    return (
        current_position_m[0] + (slot_m[0] - current_position_m[0]) * blend,
        current_position_m[1] + (slot_m[1] - current_position_m[1]) * blend,
    )


def facility_queue_extra_positions(spec: FacilityQueueSpec) -> list[tuple[float, float]]:
    apron = facility_queue_extra_positions_n(spec)
    if apron:
        return [meters(point) for point in apron]

    return []


def facility_queue_extra_positions_n(spec: FacilityQueueSpec) -> tuple[tuple[float, float], ...]:
    if spec.name in QUEUE_CAPTURE_APRONS_N:
        return QUEUE_CAPTURE_APRONS_N[spec.name]

    x, y = spec.head
    if spec.name.startswith("entry_gate"):
        points: list[tuple[float, float]] = []
        capture_bands = (
            (-0.006, 0.018),
            (-0.016, 0.024),
            (-0.030, 0.028),
            (-0.048, 0.032),
            (-0.068, 0.034),
            (-0.090, 0.036),
        )
        for dy, spread in capture_bands:
            points.extend((x + lateral * spread, y + dy) for lateral in (-1.0, -0.5, 0.0, 0.5, 1.0))
        return tuple(points)

    if spec.name.startswith("exit_gate"):
        points = []
        for row, dy in enumerate((0.012, 0.026, 0.040)):
            spread = 0.004 + row * 0.002
            points.extend(((x - spread, y + dy), (x + spread, y + dy)))
        return tuple(points)

    return ()


def facility_queue_positions(
    spec: FacilityQueueSpec, geometry: Polygon
) -> list[tuple[float, float]]:
    slot_count = max(spec.slots, spec.lanes * 5)
    positions = [pixels_to_meters(queue_slot_position_px(spec, slot)) for slot in range(slot_count)]
    positions.extend(facility_queue_extra_positions(spec))
    walkable_positions = [point for point in positions if geometry.covers(Point(point))]
    if len(walkable_positions) < 2:
        raise ValueError(f"not enough walkable queue positions for {spec.name}")
    return walkable_positions


def boarding_queue_positions(
    door_x: float,
    geometry: Polygon,
    rows: int = 10,
) -> list[tuple[float, float]]:
    positions: list[tuple[float, float]] = []
    for row in range(rows):
        for lane in range(2):
            lateral = (-0.012 if lane == 0 else 0.012) + (0.003 if row % 2 else -0.003)
            point = meters((door_x + lateral, BOARDING_QUEUE_HEAD_Y - row * 0.014))
            if geometry.covers(Point(point)):
                positions.append(point)
    if len(positions) < 2:
        raise ValueError(f"not enough walkable boarding queue positions at x={door_x}")
    return positions


def facility_kind(spec: FacilityQueueSpec) -> str:
    return PROCESS_MODEL.kind_for(spec)


def facility_queue_payload(spec: FacilityQueueSpec, geometry: Polygon) -> dict[str, object]:
    positions = facility_queue_positions(spec, geometry)
    kind = facility_kind(spec)
    return {
        "id": spec.name,
        "role": "queue",
        "kind": kind,
        "layer": "queues",
        "color": spec.color,
        "head": list(spec.head),
        "exit": list(spec.exit),
        "lanes": spec.lanes,
        "capacity": len(positions),
        "slots": [normalized_from_meters(point) for point in positions],
        "geometry": {
            "type": "queue_lane",
            "head": list(spec.head),
            "exit": list(spec.exit),
            "tail_vector": list(NATIVE_QUEUE_TAIL_VECTORS.get(spec.name, spec.tail_vector)),
        },
        "editor": {
            "pattern": "queue_lane",
            "draggable": True,
            "handles": ["head", "exit", "tail_vector"],
            "binds_to": kind,
            "regenerates": ["queue_slots", "jps_queue_stage"],
        },
    }


def boarding_queue_payloads(geometry: Polygon) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for door_index, point in enumerate(STATION_LAYOUT.control_points["platform_doors"]):
        door_x = float(point[0])
        positions = boarding_queue_positions(door_x, geometry)
        payloads.append(
            {
                "id": f"boarding_door_{door_index + 1}",
                "role": "queue",
                "kind": "boarding",
                "layer": "queues",
                "color": "#5dd45f" if door_index % 2 else "#ffd166",
                "head": [door_x, BOARDING_QUEUE_HEAD_Y],
                "exit": [door_x, BOARDING_EXIT_Y],
                "lanes": 2,
                "capacity": len(positions),
                "slots": [normalized_from_meters(position) for position in positions],
                "geometry": {
                    "type": "queue_lane",
                    "head": [door_x, BOARDING_QUEUE_HEAD_Y],
                    "exit": [door_x, BOARDING_EXIT_Y],
                    "tail_vector": [0.0, -0.014],
                },
                "editor": {
                    "pattern": "queue_lane",
                    "draggable": True,
                    "handles": ["head", "exit", "tail_vector"],
                    "binds_to": f"platform_door_{door_index + 1}",
                    "regenerates": ["queue_slots", "jps_queue_stage"],
                },
            }
        )
    return payloads


def queue_layout_payload(geometry: Polygon) -> list[dict[str, object]]:
    return [
        *(facility_queue_payload(spec, geometry) for spec in PROCESS_MODEL.native_facility_queues),
        *boarding_queue_payloads(geometry),
    ]
