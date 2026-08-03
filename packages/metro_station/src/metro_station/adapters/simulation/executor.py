"""Mesa implementation of the application simulation executor port."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from metro_station.application.simulation import (
    ProgressCallback,
    SimulationExecutionResult,
    SimulationRequest,
)

from .runtime.mesa_model import MetroStationModel
from .station.scenario import StationSandboxScenario

if TYPE_CHECKING:
    from metro_station.application.routing_plugins import EvacuationRoutingPort


class MesaSimulationExecutor:
    def __init__(
        self,
        *,
        routing_algorithm: EvacuationRoutingPort | None = None,
        routing_parameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.routing_algorithm = routing_algorithm
        self.routing_parameters = dict(routing_parameters or {})

    def execute(
        self,
        request: SimulationRequest[StationSandboxScenario],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> SimulationExecutionResult[dict[str, Any], MetroStationModel]:
        model = self.build_model(request)
        frames = model.run(progress_callback=progress_callback)
        return SimulationExecutionResult(frames=frames, runtime=model)

    def build_model(
        self,
        request: SimulationRequest[StationSandboxScenario],
    ) -> MetroStationModel:
        """Compose a model so specialized adapters can retain failure evidence."""

        return MetroStationModel(
            request.scenario,
            seed=request.seed,
            routing_algorithm=self.routing_algorithm,
            routing_parameters=self.routing_parameters,
        )
