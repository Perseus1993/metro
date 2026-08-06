from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

import mesa

from ..planning.plan import (
    FacilityStage,
)
from ..movement.backend import (
    BatchedJuPedSimMovementBackend,
    JuPedSimMovementBackend,
    MovementBackend,
)
from ..station.scenario import StationSandboxScenario
from ..station.compiler import DesignCompiler
from .spatial_queries import SpatialQueryMixin
from .physical_routing_runtime import PhysicalRoutingRuntimeMixin
from .station_graph_routing import StationGraphRoutingMixin
from .transit_routing import TransitRoutingMixin
from .passenger_demand import PassengerDemandMixin
from .passenger_departures import PassengerDepartureMixin
from .facility_queue_routing import FacilityQueueRoutingMixin
from .decision_holding import DecisionHoldingMixin
from .facility_event_runtime import FacilityEventRuntimeMixin
from .simulation_lifecycle import SimulationLifecycleMixin
from .train_exchange_runtime import TrainExchangeRuntimeMixin
from .model_initialization import initialize_metro_station_model

if TYPE_CHECKING:
    from metro_station.application.routing_plugins import EvacuationRoutingPort


class MetroStationModel(
    SimulationLifecycleMixin,
    TrainExchangeRuntimeMixin,
    FacilityEventRuntimeMixin,
    PhysicalRoutingRuntimeMixin,
    DecisionHoldingMixin,
    FacilityQueueRoutingMixin,
    StationGraphRoutingMixin,
    TransitRoutingMixin,
    PassengerDepartureMixin,
    PassengerDemandMixin,
    SpatialQueryMixin,
    mesa.Model,
):
    """Mesa model for a single-station passenger flow sandbox."""

    def __init__(
        self,
        scenario: StationSandboxScenario,
        *,
        seed: int = 42,
        movement_backend: MovementBackend | None = None,
        routing_algorithm: EvacuationRoutingPort | None = None,
        routing_parameters: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(seed=seed)
        initialize_metro_station_model(
            self,
            scenario,
            movement_backend,
            DesignCompiler,
            routing_algorithm=routing_algorithm,
            routing_parameters=routing_parameters,
            algorithm_seed=seed,
        )

    @property
    def current_time_seconds(self) -> float:
        return self.step_index * self.scenario.tick_seconds

    def _require_first(self, items: list[Any], label: str) -> Any:
        if items:
            return items[0]
        design_id = getattr(self.scenario.station_design, "id", "<unknown>")
        raise ValueError(f"Station design {design_id!r} must define at least one {label}")

    def _build_movement_backend(self) -> MovementBackend:
        requested = self.scenario.movement_backend_name
        if requested in {"jupedsim", "batched_jupedsim"} and self.jupedsim.status.available:
            return BatchedJuPedSimMovementBackend(
                self.jupedsim,
                strict=self.scenario.jupedsim_strict,
            )
        if requested == "micro_jupedsim" and self.jupedsim.status.available:
            return JuPedSimMovementBackend(
                self.jupedsim,
                strict=self.scenario.jupedsim_strict,
            )
        if requested in {"jupedsim", "batched_jupedsim", "micro_jupedsim"}:
            raise RuntimeError(
                f"JuPedSim backend {requested!r} requested but unavailable: "
                f"{self.jupedsim.status.message}"
            )
        raise ValueError(
            f"Unsupported movement backend {requested!r}. "
            "Use 'jupedsim', 'batched_jupedsim', or 'micro_jupedsim'."
        )

    def _admin_patrol_route(self, index: int) -> list[tuple[float, float]]:
        station_graph = self.layout_graph.station_graph
        if station_graph is not None:
            ordered_nodes = [
                *station_graph.nodes_matching(facility_stage=FacilityStage.ENTRY_GATE.value),
                *station_graph.nodes_matching(facility_stage=FacilityStage.VERTICAL_TRANSFER.value),
                *station_graph.nodes_matching(kind="platform"),
            ]
            route = [node.position for node in ordered_nodes]
            if route:
                offset = index % len(route)
                return route[offset:] + route[:offset]

        geom = self.layout_graph.geometry
        return [geom.paid_hall_center, geom.vertical_decision_point, geom.platform_entry]
