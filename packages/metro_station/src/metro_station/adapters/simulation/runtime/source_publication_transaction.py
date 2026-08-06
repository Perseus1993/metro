from __future__ import annotations

from typing import TYPE_CHECKING

from ..agents.passenger import PassengerAgent

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


def rollback_published_passenger(
    model: MetroStationModel,
    passenger: PassengerAgent,
) -> None:
    """Compensate a Passenger published before its source commit completed."""

    clear_facility = getattr(model, "_clear_all_facility_targeting_reservations", None)
    if callable(clear_facility):
        clear_facility(passenger)
    clear_holding = getattr(model, "_clear_all_decision_holding_reservations", None)
    if callable(clear_holding):
        clear_holding(passenger)
    remove_holding = getattr(model, "_remove_from_station_holding_areas", None)
    if callable(remove_holding):
        remove_holding(passenger)
    model.movement_backend.remove_passenger(passenger)
    try:
        model.passengers.remove(passenger)
    except ValueError:
        pass
    model.passenger_goal_runtimes.pop(int(passenger.unique_id), None)
    model.spawned_persons -= int(passenger.group_size)
    model.spawned_persons_by_intent[passenger.intent] -= int(passenger.group_size)
    if passenger.spawn_source_element_id is not None:
        model.spawned_persons_by_entrance[passenger.spawn_source_element_id] -= int(
            passenger.group_size
        )
    passenger.remove()


__all__ = ["rollback_published_passenger"]
