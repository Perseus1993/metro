from __future__ import annotations

from dataclasses import dataclass


Point = tuple[float, float]


@dataclass(frozen=True)
class FacilityServiceEvent:
    event_id: int
    facility_id: str
    facility_kind: str
    mode: str | None
    passenger_ids: tuple[int, ...]
    start_time: float
    end_time: float
    start_position: Point
    end_position: Point
    direction: str | None = None
    board_end_time: float | None = None
    arrive_time: float | None = None
    from_level: str | None = None
    to_level: str | None = None

    @property
    def count(self) -> int:
        return len(self.passenger_ids)

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "facility_id": self.facility_id,
            "facility_kind": self.facility_kind,
            "mode": self.mode,
            "passenger_ids": list(self.passenger_ids),
            "start_time": round(self.start_time, 2),
            "board_end_time": round(self.board_end_time, 2) if self.board_end_time is not None else None,
            "arrive_time": round(self.arrive_time, 2) if self.arrive_time is not None else None,
            "end_time": round(self.end_time, 2),
            "count": self.count,
            "direction": self.direction,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "start_position": list(self.start_position),
            "end_position": list(self.end_position),
        }
