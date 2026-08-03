from __future__ import annotations

import mesa

from ..planning.plan import FacilityStage
from .base import AmenityFacilityAgent, FacilityAgent
from .process import FacilityKind, FacilitySpec
from .runtime_base import BoardingDoorProcessAgent, FacilityProcessAgent, GateProcessAgent
from .vertical_runtime import (
    ElevatorProcessAgent,
    EscalatorProcessAgent,
    StairsProcessAgent,
    VerticalTransportProcessAgent,
)


def facility_agent_for_spec(model: mesa.Model, spec: FacilitySpec) -> FacilityProcessAgent:
    """Instantiate the concrete facility runtime class for a compiled spec."""

    if (
        spec.stage == FacilityStage.BOARDING_DOOR.value
        or spec.kind == FacilityKind.TRAIN_DOOR.value
    ):
        return BoardingDoorProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.GATE.value:
        return GateProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.ELEVATOR.value:
        return ElevatorProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.STAIRS.value:
        return StairsProcessAgent(model, spec=spec)
    if spec.kind == FacilityKind.ESCALATOR.value:
        return EscalatorProcessAgent(model, spec=spec)
    raise ValueError(f"Unsupported facility kind {spec.kind!r} for {spec.facility_id!r}.")


__all__ = [
    "AmenityFacilityAgent",
    "BoardingDoorProcessAgent",
    "ElevatorProcessAgent",
    "EscalatorProcessAgent",
    "FacilityAgent",
    "FacilityProcessAgent",
    "GateProcessAgent",
    "StairsProcessAgent",
    "VerticalTransportProcessAgent",
    "facility_agent_for_spec",
]
