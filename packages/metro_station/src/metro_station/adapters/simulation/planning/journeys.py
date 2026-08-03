"""Compatibility imports for the official Journey domain."""

from metro_station.domain.journeys.boarding import (
    boarding_journey_graph,
    entry_gate_journey_graph,
    station_entry_to_boarding_journey_graph,
    vertical_transfer_journey_graph,
)

__all__ = [
    "boarding_journey_graph",
    "entry_gate_journey_graph",
    "station_entry_to_boarding_journey_graph",
    "vertical_transfer_journey_graph",
]
