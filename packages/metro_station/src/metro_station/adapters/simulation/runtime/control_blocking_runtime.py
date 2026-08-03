"""Runtime semantics for deployable blocking control measures."""

from __future__ import annotations

from typing import Any, Mapping

from metro_station.application.control_plans import (
    CLOSURE_ZONE,
    DEPLOY,
    ISOLATION_BARRIER,
    WATER_BARRIER,
    ControlMeasure,
)

from .control_geometry import (
    combined_active_obstacles,
    passenger_occupies_shape,
    validate_control_shape,
)


BLOCKING_MEASURE_KINDS = frozenset({WATER_BARRIER, ISOLATION_BARRIER, CLOSURE_ZONE})


class BlockingControlRuntime:
    """Validate and apply controls that subtract walkable geometry."""

    def __init__(self) -> None:
        self.shape_by_measure_id: dict[str, Any] = {}

    def validate_model(
        self,
        model: Any,
        measures: Mapping[str, ControlMeasure],
    ) -> None:
        for measure in measures.values():
            if measure.kind in BLOCKING_MEASURE_KINDS:
                self.shape_by_measure_id[measure.measure_id] = validate_control_shape(
                    model,
                    measure,
                )

    def apply(
        self,
        model: Any,
        measure: ControlMeasure,
        action: str,
    ) -> tuple[str, dict[str, Any]]:
        shape = self.shape_by_measure_id[measure.measure_id]
        if action == DEPLOY and passenger_occupies_shape(model, measure, shape):
            return "rejected", {"reason": "passenger_occupies_deployment_geometry"}
        # The controller commits active-measure state first, then invalidates
        # geometry and reroutes against that new atomic topology.
        return "applied", {"passengers_replanned": 0}

    def active_obstacles(
        self,
        active_measure_ids: set[str],
        measures: Mapping[str, ControlMeasure],
        level_id: str | None,
    ):
        return combined_active_obstacles(
            self.shape_by_measure_id,
            active_measure_ids,
            measures,
            level_id,
        )
