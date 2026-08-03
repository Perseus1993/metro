from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable

from .events import DecisionObservation, FacilityObservation


@dataclass(frozen=True)
class FacilityCandidateCost:
    """Auditable generalized-cost components for one facility candidate."""

    facility_id: str
    eligible: bool
    ineligible_reason: str | None
    walking_seconds: float
    preference_seconds: float
    guidance_seconds: float
    avoidance_seconds: float
    queue_wait_seconds: float
    service_seconds: float
    density_persons_m2: float
    weighted_walking_seconds: float
    weighted_queue_wait_seconds: float
    weighted_service_seconds: float
    weighted_density_seconds: float
    total_seconds: float | None
    walking_distance_units: float | None
    walking_cost_source: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FacilitySelection:
    facility_id: str
    score: float
    reason: str
    action: str = "select"
    reconsider_after_seconds: float | None = None
    candidate_costs: tuple[FacilityCandidateCost, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "facility_id": self.facility_id,
            "score": self.score,
            "reason": self.reason,
            "action": self.action,
            "reconsider_after_seconds": self.reconsider_after_seconds,
            "candidate_costs": [item.as_dict() for item in self.candidate_costs],
        }


@runtime_checkable
class GoalFacilitySelector(Protocol):
    def choose(
        self,
        stage: str,
        observation: DecisionObservation,
    ) -> FacilitySelection | None: ...


@dataclass(frozen=True)
class MinimumPerceivedCostSelector:
    walking_time_weight: float = 1.0
    queue_wait_weight: float = 1.0
    service_time_weight: float = 1.0
    density_weight: float = 4.0

    def choose(
        self,
        stage: str,
        observation: DecisionObservation,
    ) -> FacilitySelection | None:
        costs = tuple(
            self._cost(candidate, stage=stage)
            for candidate in sorted(observation.candidates, key=lambda item: item.facility_id)
        )
        eligible = tuple(item for item in costs if item.eligible and item.total_seconds is not None)
        if not eligible:
            return None

        best = min(eligible, key=_eligible_cost_key)
        current = self._current_cost(eligible, observation.committed_facility_id)
        if current is not None:
            retention_reason = self._retention_reason(observation, current, best)
            if retention_reason is not None:
                return self._selection(
                    current,
                    action="retain",
                    reason=retention_reason,
                    reconsider_after_seconds=observation.reconsider_after_seconds,
                    costs=costs,
                )

        action = "switch" if current is not None else "select"
        reason = (
            "minimum_generalized_cost"
            if observation.replan_reason is None
            else "minimum_generalized_cost:forced_or_beneficial_replan"
        )
        cooldown = (
            observation.replan_cooldown_seconds
            if observation.replan_reason is not None
            else observation.commitment_duration_seconds
        )
        return self._selection(
            best,
            action=action,
            reason=reason,
            reconsider_after_seconds=observation.time_seconds + cooldown,
            costs=costs,
        )

    def _cost(self, candidate: FacilityObservation, *, stage: str) -> FacilityCandidateCost:
        ineligible_reason = _ineligible_reason(candidate, stage)
        adjusted_walking = max(
            0.0,
            candidate.walking_time_seconds
            + candidate.preference_penalty_seconds
            + candidate.guidance_adjustment_seconds
            + candidate.avoidance_penalty_seconds,
        )
        weighted_walking = adjusted_walking * self.walking_time_weight
        weighted_queue = candidate.estimated_wait_seconds * self.queue_wait_weight
        weighted_service = candidate.service_time_seconds * self.service_time_weight
        weighted_density = candidate.local_density_persons_m2 * self.density_weight
        total = weighted_walking + weighted_queue + weighted_service + weighted_density
        return FacilityCandidateCost(
            facility_id=candidate.facility_id,
            eligible=ineligible_reason is None,
            ineligible_reason=ineligible_reason,
            walking_seconds=candidate.walking_time_seconds,
            preference_seconds=candidate.preference_penalty_seconds,
            guidance_seconds=candidate.guidance_adjustment_seconds,
            avoidance_seconds=candidate.avoidance_penalty_seconds,
            queue_wait_seconds=candidate.estimated_wait_seconds,
            service_seconds=candidate.service_time_seconds,
            density_persons_m2=candidate.local_density_persons_m2,
            weighted_walking_seconds=weighted_walking,
            weighted_queue_wait_seconds=weighted_queue,
            weighted_service_seconds=weighted_service,
            weighted_density_seconds=weighted_density,
            total_seconds=None if ineligible_reason is not None else total,
            walking_distance_units=candidate.walking_distance_units,
            walking_cost_source=candidate.walking_cost_source,
        )

    @staticmethod
    def _current_cost(
        costs: tuple[FacilityCandidateCost, ...],
        facility_id: str | None,
    ) -> FacilityCandidateCost | None:
        if facility_id is None:
            return None
        return next((item for item in costs if item.facility_id == facility_id), None)

    @staticmethod
    def _retention_reason(
        observation: DecisionObservation,
        current: FacilityCandidateCost,
        best: FacilityCandidateCost,
    ) -> str | None:
        if current.facility_id == best.facility_id:
            return "hysteresis_retain:still_minimum"
        reconsider_after = observation.reconsider_after_seconds
        if reconsider_after is not None and observation.time_seconds < reconsider_after:
            return "hysteresis_retain:commitment_or_cooldown"
        current_total = current.total_seconds
        best_total = best.total_seconds
        assert current_total is not None and best_total is not None
        improvement = current_total - best_total
        if improvement < observation.minimum_improvement_seconds:
            return "hysteresis_retain:insufficient_improvement"
        return None

    @staticmethod
    def _selection(
        cost: FacilityCandidateCost,
        *,
        action: str,
        reason: str,
        reconsider_after_seconds: float | None,
        costs: tuple[FacilityCandidateCost, ...],
    ) -> FacilitySelection:
        assert cost.total_seconds is not None
        return FacilitySelection(
            facility_id=cost.facility_id,
            score=float(cost.total_seconds),
            reason=reason,
            action=action,
            reconsider_after_seconds=reconsider_after_seconds,
            candidate_costs=costs,
        )


def _ineligible_reason(candidate: FacilityObservation, stage: str) -> str | None:
    if candidate.stage != stage:
        return "wrong_stage"
    if not candidate.available:
        return "unavailable"
    if not candidate.reachable:
        return "unreachable"
    return None


def _eligible_cost_key(candidate: FacilityCandidateCost) -> tuple[float, str]:
    assert candidate.total_seconds is not None
    return candidate.total_seconds, candidate.facility_id
