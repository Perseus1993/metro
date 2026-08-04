from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

from metro_station_testkit.instant_movement_backend import (
    EndpointClearInstantMovementBackend,
)
from metro_station_acceptance.generated_acceptance_profile import (
    generated_acceptance_tier_profile,
    stratified_simulation_sample,
    trajectory_geometry_corpus,
)
from metro_station_acceptance.generated_layout_acceptance import (
    run_generated_layout_acceptance,
)
from metro_station_acceptance.generated_layout_evidence import (
    write_generated_layout_evidence,
)
from metro_station_acceptance.generated_simulation_acceptance import (
    _balanced_simulation_case_shard,
    _balanced_simulation_shard,
    run_generated_simulation_acceptance,
)
from metro_station_acceptance.invalid_layout_diagnostics import (
    inspect_invalid_layout_diagnostics,
)
from metro_station_testkit.layout_corpus import (
    corpus_coverage,
    generate_geometry_scenario_matrix,
    generate_scenario_corpus,
)
from metro_station_testkit.layout_quality import design_fingerprint, inspect_layout_quality
from metro_station_testkit.layout_recipe import LayoutRecipe, ScenarioCorpus
from metro_station_testkit.layout_scenario_generator import generate_layout


class GeneratedLayoutAcceptanceTests(unittest.TestCase):
    def test_recipe_corpus_and_generation_are_deterministic(self) -> None:
        left = generate_scenario_corpus(count=24, seed=19)
        right = generate_scenario_corpus(count=24, seed=19)

        self.assertEqual(left.as_dict(), right.as_dict())
        self.assertEqual(left, ScenarioCorpus.from_dict(left.as_dict()))
        self.assertEqual(24, len({recipe.recipe_id for recipe in left.recipes}))
        self.assertEqual(24, len({generate_layout(recipe).id for recipe in left.recipes}))

    def test_constraint_generator_builds_rich_valid_unique_layouts(self) -> None:
        corpus = generate_scenario_corpus(count=128, seed=20260716)
        fingerprints = tuple(
            design_fingerprint(generate_layout(recipe)) for recipe in corpus.recipes
        )
        coverage = corpus_coverage(corpus)

        self.assertEqual(128, len(set(fingerprints)))
        self.assertEqual({"1", "2", "3"}, set(coverage["dimensions"]["level_count"]))
        self.assertEqual(
            {"0", "1", "2", "3", "4", "5", "6"},
            set(coverage["dimensions"]["elevator_count"]),
        )

    def test_six_elevators_survive_quality_and_replay_contracts(self) -> None:
        recipe = _six_elevator_recipe()
        report = run_generated_layout_acceptance(
            ScenarioCorpus("six-elevator-corpus", 7, (recipe,))
        )

        self.assertEqual("ok", report.status, report.as_dict())
        self.assertEqual(6, report.layouts[0].replay.elevator_entity_count)
        self.assertGreaterEqual(report.layouts[0].replay.runtime_binding_count, 12)

    def test_invalid_layouts_emit_stable_expected_codes(self) -> None:
        report = inspect_invalid_layout_diagnostics()

        self.assertEqual("ok", report.status, report.as_dict())
        self.assertEqual(9, len(report.records))
        self.assertTrue(
            all(record.expected_code in record.actual_codes for record in report.records)
        )

    def test_static_acceptance_writes_reproducible_evidence(self) -> None:
        report = run_generated_layout_acceptance(generate_scenario_corpus(count=12, seed=29))

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = write_generated_layout_evidence(report, Path(temporary_directory))
            self.assertTrue(all(path.exists() for path in paths))
            self.assertTrue((Path(temporary_directory) / "corpus.json").exists())
            self.assertFalse((Path(temporary_directory) / "failures").exists())

        self.assertEqual("ok", report.status, report.as_dict())
        self.assertEqual(1.0, report.as_dict()["unique_design_rate"])

    def test_generated_designs_enter_existing_simulation_acceptance(self) -> None:
        corpus = generate_scenario_corpus(count=12, seed=31)
        report = run_generated_simulation_acceptance(
            corpus,
            tier="smoke",
            sample_size=2,
            seeds=(42,),
            include_operations=False,
            movement_backend_factory=EndpointClearInstantMovementBackend,
        )

        self.assertEqual("ok", report.status, report.as_dict())
        self.assertTrue(all(record.journeys.status == "ok" for record in report.records))
        self.assertTrue(all(record.checks["deterministic_replay"] for record in report.records))
        self.assertTrue(
            all(
                record.trajectory_gates["status"] == "not_applicable"
                and record.trajectory_gates["scientific_pass"] is None
                and record.checks["trajectory_not_applicable_explicit"]
                for record in report.records
            )
        )

    def test_tier_profile_and_sampling_freeze_scale_and_diversity(self) -> None:
        profile = generated_acceptance_tier_profile("release")
        sample = stratified_simulation_sample(
            generate_scenario_corpus(count=64, seed=37),
            12,
        )

        self.assertEqual(10_000, profile.corpus_size)
        self.assertEqual(300, profile.simulation_sample_size)
        self.assertEqual(4, len({recipe.archetype for recipe in sample}))
        self.assertEqual(5, len({recipe.operation_profile for recipe in sample}))
        self.assertEqual({0, 1, 2, 3, 4, 5, 6}, {recipe.elevator_count for recipe in sample})
        self.assertEqual(
            {"RECT", "L", "T", "NECK", "U"},
            {recipe.topology_footprint for recipe in sample},
        )
        self.assertEqual(
            {"FULL", "CHAIN", "DUAL_CLUSTER"},
            {recipe.vertical_topology for recipe in sample},
        )
        self.assertEqual(
            {"BIDIRECTIONAL", "SPLIT_ENTRY_EXIT"},
            {recipe.fare_topology for recipe in sample},
        )

    def test_trajectory_profile_freezes_sixteen_recipes_and_three_seeds(self) -> None:
        profile = generated_acceptance_tier_profile("trajectory")
        sample = stratified_simulation_sample(
            trajectory_geometry_corpus(generate_geometry_scenario_matrix()),
            profile.simulation_sample_size,
        )

        self.assertEqual(240, profile.corpus_size)
        self.assertEqual(16, profile.simulation_sample_size)
        self.assertEqual((7, 42, 99), profile.seeds)
        self.assertEqual(4, len({recipe.archetype for recipe in sample}))
        self.assertEqual(5, len({recipe.operation_profile for recipe in sample}))
        self.assertEqual(
            {0, 2, 4},
            {recipe.elevator_count for recipe in sample},
        )
        self.assertEqual(
            {"standard"},
            {recipe.asset_density for recipe in sample},
        )
        self.assertEqual(5, len({recipe.topology_footprint for recipe in sample}))
        self.assertEqual(3, len({recipe.vertical_topology for recipe in sample}))
        self.assertEqual(2, len({recipe.fare_topology for recipe in sample}))
        shards = tuple(
            _balanced_simulation_shard(
                sample,
                shard_index=index,
                shard_count=profile.simulation_sample_size,
            )
            for index in range(profile.simulation_sample_size)
        )
        self.assertTrue(all(len(shard) == 1 for shard in shards))
        self.assertEqual(
            {recipe.recipe_id for recipe in sample},
            {recipe.recipe_id for shard in shards for recipe in shard},
        )
        cases = tuple(
            (recipe, seed) for recipe in sample for seed in profile.seeds
        )
        case_shards = tuple(
            _balanced_simulation_case_shard(
                cases,
                shard_index=index,
                shard_count=len(cases),
            )
            for index in range(len(cases))
        )
        self.assertEqual(48, len(cases))
        self.assertTrue(all(len(shard) == 1 for shard in case_shards))
        self.assertEqual(set(cases), {case for shard in case_shards for case in shard})


@pytest.mark.parametrize("chunk_index", range(16))
def test_constraint_generator_quality_shard(chunk_index: int) -> None:
    """Validate the complete 128-layout corpus in watchdog-sized shards."""

    corpus = generate_scenario_corpus(count=128, seed=20260716)
    start = chunk_index * 8
    reports = tuple(
        inspect_layout_quality(generate_layout(recipe))
        for recipe in corpus.recipes[start : start + 8]
    )

    assert len(reports) == 8
    assert all(report.status == "ok" for report in reports)


def _six_elevator_recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="three-level-six-elevators",
        seed=7,
        archetype="three_level_transfer",
        entrance_count=4,
        gate_count=2,
        elevator_count=6,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=True,
        asset_density="dense",
        geometry_variant=8,
        operation_profile="train_outage",
    )


if __name__ == "__main__":
    unittest.main()
