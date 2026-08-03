from __future__ import annotations

from collections.abc import Mapping, Sequence

from .dynamic_body_clearance import (
    Point,
    constrain_motion_segment,
    external_body_positions,
    minimum_body_clearance,
)


class DynamicBodyTraceResolver:
    """Turn JuPedSim proposals into body-clear authoritative walking samples."""

    def __init__(self, model, passengers: Sequence[object]) -> None:
        self.model = model
        self._passengers = {int(item.unique_id): item for item in passengers}
        self._positions = {
            int(item.unique_id): tuple(item.pos) for item in passengers
        }
        start_time = float(model.current_time_seconds)
        self._last_time = {int(item.unique_id): start_time for item in passengers}

    def resolve(
        self,
        *,
        time_seconds: float,
        level_id: str | None,
        proposed_positions: Mapping[int, Point],
    ) -> dict[int, Point]:
        ids = tuple(sorted(int(value) for value in proposed_positions))
        resolved: dict[int, Point] = {}
        passive = external_body_positions(
            self.model,
            level_id=level_id,
            excluded_passenger_ids=ids,
            passive_only=True,
        )
        for index, passenger_id in enumerate(ids):
            passenger = self._passengers.get(passenger_id)
            if passenger is None:
                continue
            start = self._positions.get(passenger_id, tuple(passenger.pos))
            unresolved_positions = tuple(
                self._positions[other_id]
                for other_id in ids[index + 1 :]
                if other_id in self._positions
            )
            occupied = (*passive, *resolved.values(), *unresolved_positions)
            delta_seconds = max(
                0.0,
                float(time_seconds) - self._last_time.get(passenger_id, float(time_seconds)),
            )
            desired_speed = self._desired_speed(passenger)
            position, _blocked = constrain_motion_segment(
                start,
                tuple(proposed_positions[passenger_id]),
                occupied,
                minimum_distance=minimum_body_clearance(self.model),
                maximum_displacement=desired_speed * delta_seconds,
            )
            self._positions[passenger_id] = position
            self._last_time[passenger_id] = float(time_seconds)
            resolved[passenger_id] = position
        return resolved

    def position_for(self, passenger_id: int) -> Point | None:
        return self._positions.get(int(passenger_id))

    def _desired_speed(self, passenger) -> float:
        desired = getattr(self.model, "desired_walk_speed_mps", None)
        if callable(desired):
            return max(0.0, float(desired(passenger)))
        return max(
            0.0,
            float(getattr(self.model.scenario, "jupedsim_desired_speed_mps", 1.2)),
        )
