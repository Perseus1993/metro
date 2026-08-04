from __future__ import annotations

from dataclasses import dataclass
from math import exp, hypot
from typing import Protocol

from metro_station.adapters.simulation.planning.selection import pick_logit


DEFAULT_VERTICAL_CHOICE_SENSITIVITY = 2.4
WALK_DISTANCE_COST = 5.0
QUEUE_LOAD_COST = 0.08

MODE_EASE_COST = {
    "escalator": -1.8,
    "elevator": 0.35,
    "stairs": 0.25,
}


class RandomLike(Protocol):
    def random(self) -> float: ...


@dataclass(frozen=True)
class VerticalChoiceOption:
    key: str
    kind: str
    target: tuple[float, float]
    queue_load: float = 0.0
    wait_minutes: float = 0.0


def vertical_choice_cost(
    origin: tuple[float, float],
    option: VerticalChoiceOption,
) -> float:
    distance = hypot(origin[0] - option.target[0], origin[1] - option.target[1])
    return (
        distance * WALK_DISTANCE_COST
        + option.queue_load * QUEUE_LOAD_COST
        + option.wait_minutes
        + MODE_EASE_COST.get(option.kind, 0.0)
    )


def choose_vertical_option(
    rng: RandomLike,
    origin: tuple[float, float],
    options: tuple[VerticalChoiceOption, ...],
    *,
    sensitivity: float = DEFAULT_VERTICAL_CHOICE_SENSITIVITY,
) -> VerticalChoiceOption:
    return pick_logit(
        options,
        rng,
        lambda option: vertical_choice_cost(origin, option),
        sensitivity=sensitivity,
    )


def vertical_choice_probabilities(
    origin: tuple[float, float],
    options: tuple[VerticalChoiceOption, ...],
    *,
    sensitivity: float = DEFAULT_VERTICAL_CHOICE_SENSITIVITY,
) -> dict[str, float]:
    if not options:
        return {}
    costs = [(option, vertical_choice_cost(origin, option)) for option in options]
    if sensitivity <= 0.0:
        probability = 1.0 / len(options)
        return {option.key: probability for option in options}

    min_cost = min(cost for _option, cost in costs)
    weights = [
        (option, exp(max(-700.0, min(700.0, -(cost - min_cost) * sensitivity))))
        for option, cost in costs
    ]
    total = sum(weight for _option, weight in weights)
    if total <= 0.0:
        return {option.key: 0.0 for option in options}
    return {option.key: weight / total for option, weight in weights}
