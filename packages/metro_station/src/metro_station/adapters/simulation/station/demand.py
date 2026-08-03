from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, order=True)
class DemandSegment:
    start_seconds: int
    end_seconds: int
    entry_count_hour: int = 0
    exit_count_hour: int = 0
    transfer_count_hour: int = 0

    def __post_init__(self) -> None:
        if int(self.start_seconds) < 0:
            raise ValueError("demand segment start_seconds must be >= 0")
        if int(self.end_seconds) <= int(self.start_seconds):
            raise ValueError("demand segment end_seconds must be greater than start_seconds")
        for name in ("entry_count_hour", "exit_count_hour", "transfer_count_hour"):
            value = getattr(self, name)
            if int(value) < 0:
                raise ValueError(f"demand segment {name} must be >= 0")

    @property
    def duration_seconds(self) -> int:
        return int(self.end_seconds) - int(self.start_seconds)

    def groups(self, count_hour: int, group_size: int) -> int:
        persons = int(count_hour) * self.duration_seconds / 3600.0
        return max(0, round(persons / int(group_size)))


def validate_demand_segments(
    segments: tuple[DemandSegment, ...],
    *,
    horizon_seconds: float,
) -> None:
    previous_end = 0
    for segment in segments:
        if not isinstance(segment, DemandSegment):
            raise TypeError("demand_segments must contain DemandSegment")
        if segment.start_seconds < previous_end:
            raise ValueError("demand segments must be ordered and non-overlapping")
        if segment.end_seconds > horizon_seconds:
            raise ValueError("demand segment exceeds scenario horizon")
        previous_end = segment.end_seconds


def validate_entrance_weights(weights: tuple[tuple[str, float], ...]) -> None:
    ids = [str(element_id) for element_id, _ in weights]
    if len(ids) != len(set(ids)):
        raise ValueError("entry_entrance_weights must not contain duplicate entrance ids")
    if any(not element_id.strip() for element_id in ids):
        raise ValueError("entry_entrance_weights ids must not be blank")
    parsed = [float(weight) for _, weight in weights]
    if any(not isfinite(weight) or weight < 0.0 for weight in parsed):
        raise ValueError("entry_entrance_weights must contain finite non-negative weights")
    if weights and not any(weight > 0.0 for weight in parsed):
        raise ValueError("entry_entrance_weights must contain a positive weight")

