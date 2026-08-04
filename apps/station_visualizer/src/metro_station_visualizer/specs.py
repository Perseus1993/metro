from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpawnSpec:
    agent_id: int
    route_name: str
    spawn_time: float
    position: tuple[float, float]
    color: str
    size: float
    desired_speed: float
    journey_id: int
    first_stage_id: int
    radius: float = 0.24
    time_gap: float = 1.08
    group_id: int = 0
    motion_phase: float = 0.0
    motion_wobble: float = 1.0
    stride_hz: float = 1.5


@dataclass(frozen=True)
class FacilityQueueSpec:
    name: str
    source: str
    color: str
    head: tuple[float, float]
    exit: tuple[float, float]
    tail_vector: tuple[float, float]
    slots: int
    cycle: float
    first_service: float
    service_interval: float
    travel_time: float
    lanes: int = 2


FACILITY_QUEUES: tuple[FacilityQueueSpec, ...] = (
    FacilityQueueSpec(
        "down_escalator_1_queue",
        "escalator_queue_state",
        "#2f89ff",
        (0.184, 0.428),
        (0.116, 0.716),
        (-0.013, -0.014),
        16,
        30.0,
        3.2,
        0.55,
        5.7,
    ),
    FacilityQueueSpec(
        "down_escalator_2_queue",
        "escalator_queue_state",
        "#2f89ff",
        (0.490, 0.428),
        (0.540, 0.716),
        (-0.014, -0.013),
        16,
        30.0,
        3.6,
        0.55,
        5.8,
    ),
    FacilityQueueSpec(
        "down_elevator_queue",
        "elevator_queue_state",
        "#2f89ff",
        (0.612, 0.383),
        (0.650, 0.628),
        (-0.006, -0.004),
        18,
        32.0,
        8.2,
        10.5,
        6.8,
        2,
    ),
    FacilityQueueSpec(
        "up_escalator_1_queue",
        "escalator_queue_state",
        "#ff8a27",
        (0.288, 0.716),
        (0.276, 0.428),
        (-0.012, 0.015),
        7,
        30.0,
        4.4,
        0.7,
        5.9,
    ),
    FacilityQueueSpec(
        "up_escalator_2_queue",
        "escalator_queue_state",
        "#ff8a27",
        (0.815, 0.716),
        (0.776, 0.428),
        (-0.016, 0.014),
        7,
        30.0,
        4.7,
        0.7,
        5.9,
    ),
    FacilityQueueSpec(
        "stairs_down_queue",
        "stairs_queue_state",
        "#d8e5ea",
        (0.892, 0.426),
        (0.850, 0.708),
        (-0.012, -0.015),
        6,
        34.0,
        4.0,
        1.05,
        8.5,
    ),
    FacilityQueueSpec(
        "stairs_up_queue",
        "stairs_queue_state",
        "#d8e5ea",
        (0.850, 0.708),
        (0.892, 0.426),
        (0.016, 0.014),
        6,
        34.0,
        6.0,
        1.1,
        8.8,
    ),
)


GATE_QUEUE_SPECS: tuple[FacilityQueueSpec, ...] = (
    FacilityQueueSpec(
        "entry_gate_1_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.210, 0.338),
        (0.210, 0.363),
        (-0.0047, -0.007),
        18,
        18.0,
        4.0,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_2_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.235, 0.338),
        (0.235, 0.363),
        (-0.0047, -0.007),
        18,
        18.0,
        4.12,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_3_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.260, 0.338),
        (0.260, 0.363),
        (-0.0047, -0.007),
        18,
        18.0,
        4.24,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_4_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.285, 0.338),
        (0.285, 0.363),
        (-0.0047, -0.0065),
        18,
        18.0,
        4.36,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_5_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.310, 0.338),
        (0.310, 0.363),
        (-0.0047, -0.006),
        18,
        18.0,
        4.48,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_6_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.335, 0.338),
        (0.335, 0.363),
        (-0.0047, -0.006),
        18,
        18.0,
        4.60,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_7_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.800, 0.286),
        (0.800, 0.318),
        (-0.004, -0.010),
        14,
        18.0,
        4.24,
        1.65,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "entry_gate_8_queue",
        "gate_queue_state",
        "#2f89ff",
        (0.828, 0.286),
        (0.828, 0.318),
        (-0.004, -0.010),
        14,
        18.0,
        4.36,
        1.65,
        1.0,
        1,
    ),
)


EXIT_GATE_QUEUE_SPECS: tuple[FacilityQueueSpec, ...] = (
    FacilityQueueSpec(
        "exit_gate_1_queue",
        "exit_gate_queue_state",
        "#ff8a27",
        (0.744, 0.318),
        (0.744, 0.286),
        (-0.004, 0.010),
        14,
        18.0,
        4.0,
        1.35,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "exit_gate_2_queue",
        "exit_gate_queue_state",
        "#ff8a27",
        (0.772, 0.318),
        (0.772, 0.286),
        (-0.004, 0.010),
        14,
        18.0,
        4.12,
        1.35,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "exit_gate_3_queue",
        "exit_gate_queue_state",
        "#ff8a27",
        (0.800, 0.318),
        (0.800, 0.286),
        (-0.004, 0.010),
        14,
        18.0,
        4.24,
        1.35,
        1.0,
        1,
    ),
    FacilityQueueSpec(
        "exit_gate_4_queue",
        "exit_gate_queue_state",
        "#ff8a27",
        (0.828, 0.318),
        (0.828, 0.286),
        (-0.004, 0.010),
        14,
        18.0,
        4.36,
        1.35,
        1.0,
        1,
    ),
)


NATIVE_QUEUE_TAIL_VECTORS: dict[str, tuple[float, float]] = {
    "down_escalator_1_queue": (0.014, -0.006),
    "stairs_down_queue": (-0.012, -0.003),
    "stairs_up_queue": (-0.014, 0.008),
    "exit_gate_1_queue": (-0.004, 0.010),
    "exit_gate_2_queue": (-0.004, 0.010),
    "exit_gate_3_queue": (-0.004, 0.010),
    "exit_gate_4_queue": (-0.004, 0.010),
    "entry_gate_7_queue": (-0.004, -0.010),
    "entry_gate_8_queue": (-0.004, -0.010),
}
