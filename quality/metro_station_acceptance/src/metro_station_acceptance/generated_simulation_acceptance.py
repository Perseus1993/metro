from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station_testkit.layout_recipe import ScenarioCorpus

from .generated_acceptance_profile import (
    generated_acceptance_tier_profile,
    stratified_simulation_sample,
)
from .generated_simulation_run import (
    GeneratedSimulationRecord,
    run_generated_recipe_simulation,
)
from .generated_scale_acceptance import stable_recipe_shard


@dataclass(frozen=True)
class GeneratedSimulationAcceptanceReport:
    tier: str
    corpus_id: str
    seeds: tuple[int, ...]
    sampled_recipe_ids: tuple[str, ...]
    global_sampled_recipe_ids: tuple[str, ...]
    shard_index: int
    shard_count: int
    include_operations: bool
    records: tuple[GeneratedSimulationRecord, ...]
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "generated_simulation_acceptance.v1",
            "status": self.status,
            "tier": self.tier,
            "corpus_id": self.corpus_id,
            "seeds": self.seeds,
            "sampled_recipe_ids": self.sampled_recipe_ids,
            "global_sampled_recipe_ids": self.global_sampled_recipe_ids,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "include_operations": self.include_operations,
            "records": [record.as_dict() for record in self.records],
            "checks": self.checks,
        }


def run_generated_simulation_acceptance(
    corpus: ScenarioCorpus,
    *,
    tier: str = "smoke",
    sample_size: int | None = None,
    seeds: tuple[int, ...] | None = None,
    include_operations: bool = True,
    movement_backend_factory: Callable[[], MovementBackend] | None = None,
    shard_index: int = 0,
    shard_count: int = 1,
) -> GeneratedSimulationAcceptanceReport:
    profile = generated_acceptance_tier_profile(tier)
    selected_size = profile.simulation_sample_size if sample_size is None else sample_size
    selected_seeds = profile.seeds if seeds is None else seeds
    if shard_count <= 0 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("simulation shard must satisfy 0 <= shard_index < shard_count")
    global_recipes = stratified_simulation_sample(corpus, selected_size)
    recipes = tuple(
        recipe
        for recipe in global_recipes
        if stable_recipe_shard(recipe.recipe_id, shard_count) == shard_index
    )
    records = tuple(
        run_generated_recipe_simulation(
            recipe,
            selected_seeds,
            profile.normal_options,
            profile.evacuation_persons,
            profile.evacuation_minutes,
            include_operations,
            movement_backend_factory,
        )
        for recipe in recipes
    )
    checks = {
        "all_samples_reported": tuple(record.recipe_id for record in records)
        == tuple(recipe.recipe_id for recipe in recipes),
        "all_simulations_pass": all(record.status == "ok" for record in records)
        and (bool(records) or not recipes),
        "sample_size_matches_request": len(records) == selected_size,
        "global_sample_size_matches_request": len(global_recipes) == selected_size,
        "shard_sample_size_matches_assignment": len(records) == len(recipes),
        "seeds_present": bool(selected_seeds),
    }
    if shard_count > 1:
        checks["sample_size_matches_request"] = len(records) == len(recipes)
    return GeneratedSimulationAcceptanceReport(
        tier=tier,
        corpus_id=corpus.corpus_id,
        seeds=selected_seeds,
        sampled_recipe_ids=tuple(recipe.recipe_id for recipe in recipes),
        global_sampled_recipe_ids=tuple(recipe.recipe_id for recipe in global_recipes),
        shard_index=shard_index,
        shard_count=shard_count,
        include_operations=include_operations,
        records=records,
        checks=checks,
    )
