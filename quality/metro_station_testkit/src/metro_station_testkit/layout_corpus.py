from __future__ import annotations

import random
from collections import Counter
from typing import Any

from .layout_recipe import (
    ARCHETYPES,
    ASSET_DENSITIES,
    FARE_TOPOLOGIES,
    OPERATION_PROFILES,
    TOPOLOGY_FOOTPRINTS,
    VERTICAL_TOPOLOGIES,
    LayoutRecipe,
    ScenarioCorpus,
)


GEOMETRY_MATRIX_SEEDS = (7, 42)


def generate_scenario_corpus(*, count: int, seed: int = 20260716) -> ScenarioCorpus:
    if count <= 0:
        raise ValueError("scenario corpus count must be positive")
    rng = random.Random(seed)
    recipes = tuple(_recipe_for_index(index, seed, rng) for index in range(count))
    return ScenarioCorpus(
        corpus_id=f"generated-layouts-{seed}-{count}",
        seed=seed,
        recipes=recipes,
    )


def generate_geometry_scenario_matrix(
    *,
    seeds: tuple[int, ...] = GEOMETRY_MATRIX_SEEDS,
) -> ScenarioCorpus:
    """Build the constraint-aware 4x5x3x2 geometry regression matrix.

    ``CHAIN`` is not physically defined for one- or two-level stations, and no
    vertical topology exists for a one-level terminal.  The recipe therefore
    carries both the requested matrix dimension and its constraint-normalized
    effective topology.  Acceptance reports the 120 requested cells and the
    80 normalization probes separately from the 160 feasible semantic cells.
    """

    recipes: list[LayoutRecipe] = []
    for archetype_index, archetype in enumerate(ARCHETYPES):
        level_count = _level_count(archetype)
        for footprint_index, footprint in enumerate(TOPOLOGY_FOOTPRINTS):
            for topology_index, requested_topology in enumerate(VERTICAL_TOPOLOGIES):
                topology, elevator_count = _effective_geometry_topology(
                    level_count,
                    requested_topology,
                )
                for fare_index, fare_topology in enumerate(FARE_TOPOLOGIES):
                    for seed_index, seed in enumerate(seeds):
                        recipe_id = (
                            f"geometry-{archetype}-{footprint.lower()}-"
                            f"{requested_topology.lower()}-{fare_topology.lower()}-"
                            f"seed-{seed}"
                        )
                        recipes.append(
                            LayoutRecipe(
                                recipe_id=recipe_id,
                                seed=int(seed),
                                archetype=archetype,
                                entrance_count=2,
                                gate_count=(
                                    2 if fare_topology == "SPLIT_ENTRY_EXIT" else 1
                                ),
                                elevator_count=elevator_count,
                                stairs_count=0 if level_count == 1 else 1,
                                escalator_pair_count=0 if level_count == 1 else 1,
                                mirror=bool(seed_index),
                                asset_density="standard",
                                geometry_variant=(
                                    archetype_index
                                    + footprint_index
                                    + topology_index
                                    + fare_index
                                    + seed_index
                                )
                                % 9,
                                topology_footprint=footprint,
                                vertical_topology=topology,
                                requested_vertical_topology=requested_topology,
                                fare_topology=fare_topology,
                            )
                        )
    return ScenarioCorpus(
        corpus_id=f"geometry-matrix-{len(recipes)}",
        seed=0,
        recipes=tuple(recipes),
    )


def _effective_geometry_topology(
    level_count: int,
    requested: str,
) -> tuple[str, int]:
    if level_count == 1:
        return "FULL", 0
    if requested == "DUAL_CLUSTER":
        return "DUAL_CLUSTER", 4
    if requested == "CHAIN" and level_count == 3:
        return "CHAIN", 2
    return "FULL", 2


def corpus_coverage(corpus: ScenarioCorpus) -> dict[str, Any]:
    dimensions = {
        "archetype": Counter(recipe.archetype for recipe in corpus.recipes),
        "level_count": Counter(str(recipe.level_count) for recipe in corpus.recipes),
        "entrance_count": Counter(str(recipe.entrance_count) for recipe in corpus.recipes),
        "gate_count": Counter(str(recipe.gate_count) for recipe in corpus.recipes),
        "elevator_count": Counter(str(recipe.elevator_count) for recipe in corpus.recipes),
        "stairs_count": Counter(str(recipe.stairs_count) for recipe in corpus.recipes),
        "escalator_pair_count": Counter(
            str(recipe.escalator_pair_count) for recipe in corpus.recipes
        ),
        "mirror": Counter(str(recipe.mirror).lower() for recipe in corpus.recipes),
        "asset_density": Counter(recipe.asset_density for recipe in corpus.recipes),
        "operation_profile": Counter(recipe.operation_profile for recipe in corpus.recipes),
        "topology_footprint": Counter(recipe.topology_footprint for recipe in corpus.recipes),
        "vertical_topology": Counter(recipe.vertical_topology for recipe in corpus.recipes),
        "requested_vertical_topology": Counter(
            recipe.requested_vertical_topology or recipe.vertical_topology
            for recipe in corpus.recipes
        ),
        "fare_topology": Counter(recipe.fare_topology for recipe in corpus.recipes),
    }
    elevator_level_pairs = Counter(
        f"levels={recipe.level_count},elevators={recipe.elevator_count}"
        for recipe in corpus.recipes
    )
    return {
        "recipe_count": len(corpus.recipes),
        "dimensions": {name: dict(sorted(counts.items())) for name, counts in dimensions.items()},
        "pairs": {"level_count_x_elevator_count": dict(sorted(elevator_level_pairs.items()))},
    }


def _recipe_for_index(index: int, corpus_seed: int, rng: random.Random) -> LayoutRecipe:
    archetype = ARCHETYPES[index % len(ARCHETYPES)]
    level_count = _level_count(archetype)
    cycle = index // len(ARCHETYPES)
    entrance_count = 1 + ((cycle + index) % 4)
    if archetype == "two_level_multi_access":
        entrance_count = max(2, entrance_count)
    elevator_count = 0 if level_count == 1 else 1 + (cycle % 6)
    gate_count = 1 + ((cycle + index // 2) % 2)
    vertical_topology = "FULL"
    if archetype == "three_level_transfer" and elevator_count == 2 and cycle % 3 == 1:
        vertical_topology = "CHAIN"
    elif level_count > 1 and elevator_count >= 4 and cycle % 3 == 2:
        vertical_topology = "DUAL_CLUSTER"
    fare_topology = (
        "SPLIT_ENTRY_EXIT" if gate_count == 2 and (cycle + index) % 2 else "BIDIRECTIONAL"
    )
    return LayoutRecipe(
        recipe_id=f"layout-{corpus_seed}-{index:05d}",
        seed=rng.randrange(0, 2**31),
        archetype=archetype,
        entrance_count=entrance_count,
        gate_count=gate_count,
        elevator_count=elevator_count,
        stairs_count=0 if level_count == 1 else (cycle + index) % 2,
        escalator_pair_count=0 if level_count == 1 else (cycle + index // 3) % 2,
        mirror=bool(rng.randrange(2)),
        asset_density=ASSET_DENSITIES[(cycle + index) % len(ASSET_DENSITIES)],
        geometry_variant=rng.randrange(9),
        operation_profile=OPERATION_PROFILES[
            (cycle + (index % len(ARCHETYPES)) * 2) % len(OPERATION_PROFILES)
        ],
        topology_footprint=TOPOLOGY_FOOTPRINTS[
            (cycle * 2 + index) % len(TOPOLOGY_FOOTPRINTS)
        ],
        vertical_topology=vertical_topology,
        fare_topology=fare_topology,
    )


def _level_count(archetype: str) -> int:
    return {
        "single_terminal": 1,
        "two_level_island": 2,
        "two_level_multi_access": 2,
        "three_level_transfer": 3,
    }[archetype]
