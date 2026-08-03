"""Compatibility imports for the official Journey domain."""

from metro_station.domain.journeys.catalog import (
    JourneyGraphCatalog,
    default_journey_graph_catalog,
    load_journey_graph_catalog,
)

__all__ = [
    "JourneyGraphCatalog",
    "default_journey_graph_catalog",
    "load_journey_graph_catalog",
]
