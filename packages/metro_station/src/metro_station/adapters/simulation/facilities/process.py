from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import hypot

from .vertical import VerticalFacilityConfig


Point = tuple[float, float]

DEFAULT_FALLBACK_QUEUE_SPACING = 0.8
DEFAULT_FALLBACK_QUEUE_CAPACITY = 8
DEFAULT_RELEASE_SPACING_MIN = 0.42
DEFAULT_RELEASE_SPACING_MAX = 0.70
DEFAULT_RELEASE_FORWARD_EXTRA = 5


class FacilityKind(StrEnum):
    AMENITY = "amenity"
    GATE = "gate"
    ESCALATOR = "escalator"
    ELEVATOR = "elevator"
    STAIRS = "stairs"
    TRAIN_DOOR = "train_door"


@dataclass(frozen=True)
class QueueLayout:
    anchor: Point
    per_row: int
    col_step: Point
    row_step: Point
    slots: tuple[Point, ...] = ()

    def slot(self, index: int) -> Point:
        if self.slots:
            if index < len(self.slots):
                return self.slots[index]
            return self._overflow_slot(index)
        row = index // self.per_row
        col = index % self.per_row
        return (
            self.anchor[0] + col * self.col_step[0] + row * self.row_step[0],
            self.anchor[1] + col * self.col_step[1] + row * self.row_step[1],
        )

    def _overflow_slot(self, index: int) -> Point:
        tail = self._overflow_tail()
        overflow_index = index - len(self.slots)
        base = tail[overflow_index % len(tail)]
        row = 1 + overflow_index // len(tail)
        step = self._overflow_step()
        return (base[0] + row * step[0], base[1] + row * step[1])

    def _overflow_tail(self) -> tuple[Point, ...]:
        tail_size = max(1, min(max(1, self.per_row), len(self.slots)))
        return self.slots[-tail_size:]

    def _overflow_step(self) -> Point:
        if hypot(*self.row_step) > 0.001:
            return self.row_step

        inferred = self._inferred_slot_axis()
        if inferred is not None:
            return inferred

        if hypot(*self.col_step) > 0.001:
            return (-self.col_step[1], self.col_step[0])
        return (0.0, 0.8)

    def _inferred_slot_axis(self) -> Point | None:
        if len(self.slots) < 2:
            return None

        band_size = max(1, min(max(1, self.per_row), len(self.slots) // 2))
        head = self.slots[:band_size]
        tail = self.slots[-band_size:]
        head_center = _centroid(head)
        tail_center = _centroid(tail)
        dx = tail_center[0] - head_center[0]
        dy = tail_center[1] - head_center[1]
        length = hypot(dx, dy)
        if length <= 0.001:
            return None

        spacing = self._inferred_spacing()
        return (dx / length * spacing, dy / length * spacing)

    def _inferred_spacing(self) -> float:
        distances: list[float] = []
        for left in self.slots[:12]:
            for right in self.slots[:12]:
                distance = hypot(left[0] - right[0], left[1] - right[1])
                if distance > 0.05:
                    distances.append(distance)
        if not distances:
            return 0.8
        return max(0.35, min(1.2, min(distances)))


def _centroid(points: tuple[Point, ...]) -> Point:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


@dataclass(frozen=True)
class QueueCrossingGuard:
    enabled: bool = False
    tolerance_units: float = 0.0
    lane_half_width_units: float = 0.0


@dataclass(frozen=True)
class FacilitySpec:
    facility_id: str
    stage: str
    label: str
    kind: str
    direction: str
    position: Point
    queue_layout: QueueLayout
    exit_position: Point
    service_persons_per_min: int
    queue_state: str
    service_state: str
    release_route: tuple[Point, ...]
    speed_units_per_tick: float | None = None
    travel_speed_m_s: float | None = None
    train_gated: bool = False
    train_capacity_limited: bool = False
    line_id: str = "default"
    platform_id: str | None = None
    entry_level_id: str | None = None
    exit_level_id: str | None = None
    source_element_id: str | None = None
    vertical_config: VerticalFacilityConfig | None = None
    traversal_width_m: float | None = None
    release_column_count: int = 3
    release_spacing_min: float = DEFAULT_RELEASE_SPACING_MIN
    release_spacing_max: float = DEFAULT_RELEASE_SPACING_MAX
    release_clearance_pad: float = 0.04
    release_personal_factor: float = 0.55
    release_lateral_range: int = 3
    release_forward_extra: int = DEFAULT_RELEASE_FORWARD_EXTRA
    fallback_queue_spacing: float = DEFAULT_FALLBACK_QUEUE_SPACING
    fallback_queue_capacity: int = DEFAULT_FALLBACK_QUEUE_CAPACITY
    queue_crossing_guard: QueueCrossingGuard = field(default_factory=QueueCrossingGuard)
    # Optional geometry-authored outward unit vector at the exit portal.
    # This is essential for stacked connectors whose entry and exit share XY;
    # queue offsets and graph representative points are not portal normals.
    release_forward_hint: Point | None = None

    @property
    def queue_anchor(self) -> Point:
        return self.queue_layout.anchor

    @property
    def persons_per_min(self) -> int:
        return self.service_persons_per_min
