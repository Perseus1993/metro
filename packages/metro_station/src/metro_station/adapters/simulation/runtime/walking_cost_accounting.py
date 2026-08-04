from __future__ import annotations

from enum import StrEnum
from typing import Any


class WalkingCostConfigurationError(RuntimeError):
    """A production walking-cost query cannot provide auditable physical evidence."""


class WalkingCostSource(StrEnum):
    """Closed vocabulary for physical walking-cost evaluation outcomes."""

    PHYSICAL_WAYPOINT_GEODESIC = "physical_waypoint_geodesic"
    PHYSICAL_ROUTE_UNREACHABLE = "physical_route_unreachable"
    PHYSICAL_ROUTE_ERROR = "physical_route_error"
    PROVIDER_MISSING = "provider_missing"
    EUCLIDEAN_FALLBACK = "euclidean_fallback"


WALKING_COST_SOURCE_NAMES = frozenset(source.value for source in WalkingCostSource)


def record_walking_cost_source(model: Any, source: str) -> None:
    """Record exactly one attempted physical walking-cost evaluation."""

    try:
        source_name = WalkingCostSource(str(source)).value
    except ValueError as exc:
        raise WalkingCostConfigurationError(
            f"unknown walking-cost source {source!r}"
        ) from exc
    counts = getattr(model, "walking_cost_source_counts", None)
    if counts is None:
        raise WalkingCostConfigurationError(
            "model walking-cost metrics were not initialized"
        )
    counts[source_name] += 1
    model.walking_cost_evaluation_count += 1


__all__ = [
    "WALKING_COST_SOURCE_NAMES",
    "WalkingCostConfigurationError",
    "WalkingCostSource",
    "record_walking_cost_source",
]
