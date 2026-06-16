from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..planning.plan import AgentIntent, FacilityStage
from math import hypot

from .filters import filter_facilities_for_passenger
from .process import FacilityKind
from ..planning.selection import pick_logit

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .runtime import FacilityProcessAgent
    from ..runtime.mesa_model import MetroStationModel


class FacilityChoicePolicy(ABC):
    """Strategy hook for choosing among candidate station facilities."""

    @abstractmethod
    def choose(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        stage: str,
        candidates: list[FacilityProcessAgent],
    ) -> FacilityProcessAgent:
        """Return the facility the passenger should target next."""


class DefaultFacilityChoicePolicy(FacilityChoicePolicy):
    """Current passenger choice behavior, extracted from the model."""

    def choose(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        stage: str,
        candidates: list[FacilityProcessAgent],
    ) -> FacilityProcessAgent:
        if not candidates:
            raise ValueError(f"No facilities are configured for stage {stage!r}")
        candidates = filter_facilities_for_passenger(passenger, stage, candidates)
        if not candidates:
            raise ValueError(f"No facilities match passenger constraints for stage {stage!r}")
        if stage == FacilityStage.VERTICAL_TRANSFER.value:
            candidates = self._vertical_preference_candidates(model, passenger, candidates)
        candidates = self._without_avoided_facilities(passenger, stage, candidates)
        if not candidates:
            raise ValueError(f"No unavoided facilities remain for stage {stage!r}")
        available = [candidate for candidate in candidates if candidate.is_available_for_choice]
        if available:
            candidates = available
        return pick_logit(
            candidates,
            model.random,
            lambda item: self._generalized_cost(model, passenger, stage, item),
            sensitivity=model.scenario.facility_choice_logit_sensitivity,
        )

    def _vertical_preference_candidates(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        candidates: list[FacilityProcessAgent],
    ) -> list[FacilityProcessAgent]:
        direction = "up" if passenger.intent == AgentIntent.EXIT_STATION.value else "down"
        direction_candidates = [
            item for item in candidates if item.spec.direction in {direction, "both"}
        ]
        filtered = direction_candidates
        if passenger.prefers_elevator:
            elevator_candidates = [
                item for item in filtered if item.spec.kind == FacilityKind.ELEVATOR.value
            ]
            if elevator_candidates:
                filtered = elevator_candidates
        elif passenger.prefers_stairs:
            stairs_candidates = [
                item for item in filtered if item.spec.kind == FacilityKind.STAIRS.value
            ]
            if stairs_candidates:
                filtered = stairs_candidates
        elif direction_candidates:
            directed_candidates = [
                item for item in filtered if item.spec.kind != FacilityKind.ELEVATOR.value
            ]
            if directed_candidates:
                filtered = directed_candidates
        return filtered

    def _without_avoided_facilities(
        self,
        passenger: PassengerAgent,
        stage: str,
        candidates: list[FacilityProcessAgent],
    ) -> list[FacilityProcessAgent]:
        avoided = getattr(passenger, "avoided_facility_ids_by_stage", {}).get(stage, set())
        if not avoided:
            return candidates
        fresh = [candidate for candidate in candidates if candidate.facility_id not in avoided]
        return fresh

    def _generalized_cost(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        stage: str,
        facility: FacilityProcessAgent,
    ) -> float:
        px, py = passenger.pos
        qx, qy = facility.spec.queue_anchor
        walking_distance = hypot(px - qx, py - qy)
        walking_time_min = (
            walking_distance
            / max(0.001, model.scenario.walk_units_per_tick)
            * model.scenario.tick_seconds
            / 60.0
        )
        queue_delay_min = facility.queue_persons / max(
            1.0,
            facility.effective_service_persons_per_min,
        )
        return (
            walking_time_min
            + queue_delay_min
            + self._facility_penalty(passenger, stage, facility)
            + self._replan_penalty(model, passenger, stage, facility)
        )

    def _facility_penalty(
        self,
        passenger: PassengerAgent,
        stage: str,
        facility: FacilityProcessAgent,
    ) -> float:
        if stage != FacilityStage.VERTICAL_TRANSFER.value:
            return 0.0
        if not facility.is_available_for_choice:
            return 999.0
        if passenger.prefers_elevator and facility.spec.kind != FacilityKind.ELEVATOR.value:
            return 1.2
        if passenger.prefers_stairs and facility.spec.kind != FacilityKind.STAIRS.value:
            return 0.8
        if facility.spec.kind == FacilityKind.STAIRS.value:
            return float(getattr(facility, "fatigue_cost", 0.0))
        if not passenger.prefers_elevator and facility.spec.kind == FacilityKind.ELEVATOR.value:
            return 0.25
        return 0.0

    def _replan_penalty(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        stage: str,
        facility: FacilityProcessAgent,
    ) -> float:
        avoided = getattr(passenger, "avoided_facility_ids_by_stage", {}).get(stage, set())
        if facility.facility_id not in avoided:
            return 0.0
        return model.scenario.replan_avoided_facility_penalty


class StaffGuidedPolicy(DefaultFacilityChoicePolicy):
    """Policy extension point for staff/admin intervention."""

    def __init__(self) -> None:
        self._facility_overrides: dict[int, str] = {}

    def guide_passenger(self, passenger_id: int, facility_id: str) -> None:
        self._facility_overrides[passenger_id] = facility_id

    def clear_guidance(self, passenger_id: int) -> None:
        self._facility_overrides.pop(passenger_id, None)

    def choose(
        self,
        model: MetroStationModel,
        passenger: PassengerAgent,
        stage: str,
        candidates: list[FacilityProcessAgent],
    ) -> FacilityProcessAgent:
        guided_facility_id = self._facility_overrides.get(passenger.unique_id)
        if guided_facility_id is not None:
            for candidate in candidates:
                if candidate.facility_id == guided_facility_id:
                    self.clear_guidance(passenger.unique_id)
                    return candidate
            self.clear_guidance(passenger.unique_id)
        return super().choose(model, passenger, stage, candidates)
