from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PassengerTerminalEvent:
    passenger_id: int
    intent: str
    event: str
    time_seconds: float
    duration_seconds: float
    persons: int

    def as_dict(self) -> dict[str, int | float | str]:
        return asdict(self)
