"""Compatibility imports for official Journey serialization."""

from metro_station.domain.journeys.serialization import (
    journey_graph_from_mapping,
    journey_graph_to_dict,
)

__all__ = ["journey_graph_from_mapping", "journey_graph_to_dict"]
