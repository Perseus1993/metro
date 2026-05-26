from __future__ import annotations

from collections.abc import Callable, Sequence
from math import exp
from typing import Protocol, TypeVar


class RandomLike(Protocol):
    def random(self) -> float: ...


T = TypeVar("T")


def pick_least_loaded(
    candidates: Sequence[T],
    rng: RandomLike,
    load: Callable[[T], float],
) -> T:
    """Pick the lowest-load item, using randomness only to break ties."""

    return min(candidates, key=lambda item: (load(item), rng.random()))


def pick_logit(
    candidates: Sequence[T],
    rng: RandomLike,
    cost: Callable[[T], float],
    *,
    sensitivity: float,
) -> T:
    """Pick from candidates with multinomial logit probabilities.

    Lower-cost candidates are more likely, but alternatives retain a non-zero
    chance when sensitivity is finite. Costs are shifted by the minimum cost for
    numerical stability.
    """

    if not candidates:
        raise ValueError("pick_logit requires at least one candidate")
    if len(candidates) == 1:
        return candidates[0]

    scored = [(item, float(cost(item))) for item in candidates]
    if sensitivity <= 0.0:
        index = min(int(rng.random() * len(scored)), len(scored) - 1)
        return scored[index][0]

    min_cost = min(score for _item, score in scored)
    weights = [
        exp(max(-700.0, min(700.0, -(score - min_cost) * sensitivity))) for _item, score in scored
    ]
    total = sum(weights)
    if total <= 0.0:
        return min(scored, key=lambda pair: (pair[1], rng.random()))[0]

    draw = rng.random() * total
    cumulative = 0.0
    for (item, _score), weight in zip(scored, weights):
        cumulative += weight
        if draw <= cumulative:
            return item
    return scored[-1][0]
