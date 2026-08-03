from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from metro_station_testkit.layout_recipe import LayoutRecipe, ScenarioCorpus


@dataclass(frozen=True)
class GeneratedAcceptanceTierProfile:
    tier: str
    corpus_size: int
    simulation_sample_size: int
    seeds: tuple[int, ...]
    normal_options: dict[str, int]
    evacuation_persons: int
    evacuation_minutes: int


def generated_acceptance_tier_profile(tier: str) -> GeneratedAcceptanceTierProfile:
    profiles = {
        "smoke": GeneratedAcceptanceTierProfile(
            "smoke",
            64,
            12,
            (42,),
            _normal_options(120, 120, 120, 2, 25),
            12,
            8,
        ),
        "nightly": GeneratedAcceptanceTierProfile(
            "nightly",
            2_000,
            150,
            (41, 42, 43),
            _normal_options(600, 300, 300, 3, 17),
            20,
            6,
        ),
        "release": GeneratedAcceptanceTierProfile(
            "release",
            10_000,
            300,
            (41, 42, 43),
            _normal_options(1800, 900, 900, 5, 25),
            30,
            8,
        ),
    }
    try:
        return profiles[tier]
    except KeyError as exc:
        raise ValueError("generated acceptance tier must be smoke, nightly, or release") from exc


def stratified_simulation_sample(
    corpus: ScenarioCorpus,
    sample_size: int,
) -> tuple[LayoutRecipe, ...]:
    if sample_size < 0:
        raise ValueError("simulation sample size cannot be negative")
    if sample_size == 0:
        return ()
    if sample_size > len(corpus.recipes):
        raise ValueError("simulation sample size cannot exceed corpus size")
    remaining = list(enumerate(corpus.recipes))
    result: list[LayoutRecipe] = []
    archetypes: Counter[str] = Counter()
    elevator_counts: Counter[int] = Counter()
    operation_profiles: Counter[str] = Counter()
    asset_densities: Counter[str] = Counter()
    topology_footprints: Counter[str] = Counter()
    vertical_topologies: Counter[str] = Counter()
    fare_topologies: Counter[str] = Counter()
    while len(result) < sample_size:
        selected_index, (_, selected) = min(
            enumerate(remaining),
            key=lambda item: _sample_score(
                item[1],
                archetypes,
                elevator_counts,
                operation_profiles,
                asset_densities,
                topology_footprints,
                vertical_topologies,
                fare_topologies,
            ),
        )
        remaining.pop(selected_index)
        result.append(selected)
        archetypes[selected.archetype] += 1
        elevator_counts[selected.elevator_count] += 1
        operation_profiles[selected.operation_profile] += 1
        asset_densities[selected.asset_density] += 1
        topology_footprints[selected.topology_footprint] += 1
        vertical_topologies[selected.vertical_topology] += 1
        fare_topologies[selected.fare_topology] += 1
    return tuple(result)


def _sample_score(
    indexed_recipe: tuple[int, LayoutRecipe],
    archetypes: Counter[str],
    elevator_counts: Counter[int],
    operation_profiles: Counter[str],
    asset_densities: Counter[str],
    topology_footprints: Counter[str],
    vertical_topologies: Counter[str],
    fare_topologies: Counter[str],
) -> tuple[int, ...]:
    index, recipe = indexed_recipe
    counts = (
        operation_profiles[recipe.operation_profile],
        archetypes[recipe.archetype],
        elevator_counts[recipe.elevator_count],
        asset_densities[recipe.asset_density],
        topology_footprints[recipe.topology_footprint],
        vertical_topologies[recipe.vertical_topology],
        fare_topologies[recipe.fare_topology],
    )
    return (
        counts[0],
        counts[2],
        counts[1],
        sum(counts),
        counts[3],
        counts[4],
        counts[5],
        counts[6],
        index,
    )


def _normal_options(
    entry_count_hour: int,
    exit_count_hour: int,
    transfer_count_hour: int,
    demand_minutes: int,
    clearance_minutes: int,
) -> dict[str, int]:
    return {
        "entry_count_hour": entry_count_hour,
        "exit_count_hour": exit_count_hour,
        "transfer_count_hour": transfer_count_hour,
        "demand_minutes": demand_minutes,
        "clearance_minutes": clearance_minutes,
    }
