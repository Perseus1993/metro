from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from metro_station.adapters.simulation.movement.backend import MovementBackend
from metro_station_testkit.layout_recipe import LayoutRecipe, ScenarioCorpus

from .generated_acceptance_profile import (
    generated_acceptance_tier_profile,
    stratified_simulation_sample,
)
from .generated_simulation_run import (
    GeneratedSimulationRecord,
    run_generated_recipe_simulation,
)


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
    sampled_case_ids: tuple[str, ...] = ()
    global_sampled_case_ids: tuple[str, ...] = ()
    shard_algorithm: str = "recipe_index_modulo"

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    @property
    def trajectory_scientific_status(self) -> str:
        statuses = {record.trajectory_scientific_status for record in self.records}
        if not statuses:
            return "not_evaluated"
        if statuses == {"pass"}:
            return "pass"
        if statuses == {"not_applicable"}:
            return "not_applicable"
        return "fail"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "generated_simulation_acceptance.v1",
            "status": self.status,
            "tier": self.tier,
            "corpus_id": self.corpus_id,
            "seeds": self.seeds,
            "sampled_recipe_ids": self.sampled_recipe_ids,
            "global_sampled_recipe_ids": self.global_sampled_recipe_ids,
            "sampled_case_ids": self.sampled_case_ids,
            "global_sampled_case_ids": self.global_sampled_case_ids,
            "shard_algorithm": self.shard_algorithm,
            "shard_index": self.shard_index,
            "shard_count": self.shard_count,
            "include_operations": self.include_operations,
            "trajectory_scientific_status": self.trajectory_scientific_status,
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
    shard_by_seed: bool = False,
) -> GeneratedSimulationAcceptanceReport:
    profile = generated_acceptance_tier_profile(tier)
    selected_size = profile.simulation_sample_size if sample_size is None else sample_size
    selected_seeds = profile.seeds if seeds is None else seeds
    if not selected_seeds:
        raise ValueError("generated simulation acceptance requires at least one seed")
    if len(selected_seeds) != len(set(selected_seeds)):
        raise ValueError("generated simulation acceptance seeds must be unique")
    if shard_count <= 0 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("simulation shard must satisfy 0 <= shard_index < shard_count")
    global_recipes = stratified_simulation_sample(corpus, selected_size)
    global_cases = tuple(
        (recipe, seed) for recipe in global_recipes for seed in selected_seeds
    )
    if shard_by_seed:
        cases = _balanced_simulation_case_shard(
            global_cases,
            shard_index=shard_index,
            shard_count=shard_count,
        )
        recipes = tuple(recipe for recipe, _seed in cases)
        record_seeds = tuple((seed,) for _recipe, seed in cases)
        shard_algorithm = "recipe_seed_index_modulo"
    else:
        recipes = _balanced_simulation_shard(
            global_recipes,
            shard_index=shard_index,
            shard_count=shard_count,
        )
        record_seeds = tuple(selected_seeds for _recipe in recipes)
        cases = tuple(
            (recipe, seed) for recipe in recipes for seed in selected_seeds
        )
        shard_algorithm = "recipe_index_modulo"
    records = tuple(
        run_generated_recipe_simulation(
            recipe,
            seeds_for_record,
            profile.normal_options,
            profile.evacuation_persons,
            profile.evacuation_minutes,
            include_operations,
            movement_backend_factory,
        )
        for recipe, seeds_for_record in zip(recipes, record_seeds, strict=True)
    )
    sampled_case_ids = (
        tuple(_simulation_case_id(recipe, seed) for recipe, seed in cases)
        if shard_by_seed
        else ()
    )
    global_case_ids = (
        tuple(_simulation_case_id(recipe, seed) for recipe, seed in global_cases)
        if shard_by_seed
        else ()
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
        "trajectory_status_explicit": all(
            record.trajectory_gates is not None
            and record.trajectory_scientific_status
            in {"pass", "fail", "not_applicable"}
            for record in records
        )
        and (bool(records) or not recipes),
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
        sampled_case_ids=sampled_case_ids,
        global_sampled_case_ids=global_case_ids,
        shard_algorithm=shard_algorithm,
    )


def _balanced_simulation_shard(
    recipes: tuple[LayoutRecipe, ...],
    *,
    shard_index: int,
    shard_count: int,
) -> tuple[LayoutRecipe, ...]:
    """Partition the frozen stratified sample with at most one-record skew.

    Hash sharding is appropriate for large generated corpora, but a 16-record
    scientific sample can otherwise produce empty shards and three-record
    outliers.  The sample order is already deterministic, so index modulo is
    stable and gives every watchdog-sized shard a bounded amount of work.
    """

    return tuple(recipes[shard_index::shard_count])


def _balanced_simulation_case_shard(
    cases: tuple[tuple[LayoutRecipe, int], ...],
    *,
    shard_index: int,
    shard_count: int,
) -> tuple[tuple[LayoutRecipe, int], ...]:
    """Partition recipe/seed cases without changing the scientific matrix."""

    return tuple(cases[shard_index::shard_count])


def _simulation_case_id(recipe: LayoutRecipe, seed: int) -> str:
    return f"{recipe.recipe_id}::seed={int(seed)}"
