from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, isfinite
from typing import Protocol


class RandomLike(Protocol):
    def random(self) -> float: ...


@dataclass(frozen=True)
class QueueFieldCandidate:
    stage_id: int
    facility: str | None
    distance_m: float
    load: int
    service_interval_s: float
    current: bool
    reachable: bool


@dataclass(frozen=True)
class QueueFieldScore:
    stage_id: int
    facility: str | None
    reachable: bool
    current: bool
    distance_m: float
    load: int
    service_interval_s: float
    cost: float


@dataclass(frozen=True)
class QueueAttractivenessField:
    """Low-frequency field used when a target queue remains unattractive.

    This does not force a passenger to abandon a queue. It makes alternatives
    more tempting only when the current target has become costly in the local
    field because of distance, crowd load, slow service, and stalled targeting.
    """

    distance_weight: float = 0.18
    load_weight: float = 0.72
    service_weight: float = 0.08
    current_stall_penalty: float = 1.15
    switch_penalty: float = 0.85
    sensitivity: float = 1.15

    def rank(self, candidates: Sequence[QueueFieldCandidate]) -> tuple[QueueFieldScore, ...]:
        scores = [
            QueueFieldScore(
                stage_id=candidate.stage_id,
                facility=candidate.facility,
                reachable=candidate.reachable,
                current=candidate.current,
                distance_m=candidate.distance_m,
                load=candidate.load,
                service_interval_s=candidate.service_interval_s,
                cost=self._cost(candidate),
            )
            for candidate in candidates
        ]
        return tuple(sorted(scores, key=lambda item: (item.cost, item.stage_id)))

    def choose(
        self, candidates: Sequence[QueueFieldCandidate], rng: RandomLike
    ) -> QueueFieldScore | None:
        scores = [
            score for score in self.rank(candidates) if score.reachable and isfinite(score.cost)
        ]
        if not scores:
            return None
        if len(scores) == 1:
            return scores[0]

        min_cost = min(score.cost for score in scores)
        weights = [
            exp(max(-700.0, min(700.0, -(score.cost - min_cost) * self.sensitivity)))
            for score in scores
        ]
        total = sum(weights)
        if total <= 0.0:
            return min(scores, key=lambda item: (item.cost, rng.random()))

        draw = rng.random() * total
        cumulative = 0.0
        for score, weight in zip(scores, weights):
            cumulative += weight
            if draw <= cumulative:
                return score
        return scores[-1]

    def _cost(self, candidate: QueueFieldCandidate) -> float:
        if not candidate.reachable:
            return float("inf")
        return (
            candidate.distance_m * self.distance_weight
            + candidate.load * self.load_weight
            + candidate.service_interval_s * self.service_weight
            + (self.current_stall_penalty if candidate.current else self.switch_penalty)
        )
