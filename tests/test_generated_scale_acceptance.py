from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from metro_station_acceptance.generated_scale_acceptance import (
    merge_generated_scale_shards,
    merge_generated_simulation_shards,
    run_generated_scale_shard,
    stable_recipe_shard,
)
from metro_station_acceptance.generated_simulation_acceptance import (
    run_generated_simulation_acceptance,
)
from metro_station_testkit.instant_movement_backend import (
    EndpointClearInstantMovementBackend,
)
from metro_station_acceptance.generated_scale_evidence import (
    load_generated_scale_resume,
    write_generated_scale_evidence,
    write_generated_scale_record_checkpoint,
)
from metro_station_testkit.layout_corpus import generate_scenario_corpus


def test_stable_recipe_sharding_is_deterministic_and_total() -> None:
    recipe_ids = tuple(f"recipe-{index:03d}" for index in range(100))

    left = tuple(stable_recipe_shard(recipe_id, 4) for recipe_id in recipe_ids)
    right = tuple(stable_recipe_shard(recipe_id, 4) for recipe_id in recipe_ids)

    assert left == right
    assert set(left) == {0, 1, 2, 3}
    assert all(0 <= shard < 4 for shard in left)


def test_serial_two_shard_and_four_shard_canonical_results_are_identical() -> None:
    corpus = generate_scenario_corpus(count=16, seed=20261101)

    serial = merge_generated_scale_shards((run_generated_scale_shard(corpus),))
    inspected_records = {
        str(record["recipe_id"]): deepcopy(record) for record in serial["records"]
    }

    def cached_inspection(recipe):
        record = inspected_records[recipe.recipe_id]
        return SimpleNamespace(as_dict=lambda: deepcopy(record))

    # Sharding and merging must not require re-running the expensive layout
    # inspection.  The serial pass above supplies real canonical records; the
    # cached passes isolate the distribution/merge invariant this test owns.
    with patch(
        "metro_station_acceptance.generated_scale_acceptance.inspect_generated_recipe",
        side_effect=cached_inspection,
    ):
        two = merge_generated_scale_shards(
            tuple(
                run_generated_scale_shard(corpus, shard_index=index, shard_count=2)
                for index in range(2)
            )
        )
        four = merge_generated_scale_shards(
            tuple(
                run_generated_scale_shard(corpus, shard_index=index, shard_count=4)
                for index in range(4)
            )
        )

    assert serial["status"] == two["status"] == four["status"] == "ok"
    assert serial["canonical_fingerprint"] == two["canonical_fingerprint"]
    assert serial["canonical_fingerprint"] == four["canonical_fingerprint"]
    assert len(serial["records"]) == len(two["records"]) == len(four["records"]) == 16


def test_interrupted_checkpoint_resume_skips_completed_cases_without_overwrite(
    tmp_path: Path,
) -> None:
    corpus = generate_scenario_corpus(count=24, seed=20261102)
    checkpoint_dir = tmp_path / "checkpoint"
    partial = run_generated_scale_shard(
        corpus,
        shard_index=1,
        shard_count=2,
        max_new_cases=5,
        on_record=lambda record, progress: write_generated_scale_record_checkpoint(
            checkpoint_dir,
            record,
            progress,
        ),
    )
    assert partial["status"] == "review"
    assert len(partial["records"]) == 5
    resume_payload = load_generated_scale_resume(checkpoint_dir)
    resumed = run_generated_scale_shard(
        corpus,
        shard_index=1,
        shard_count=2,
        resume_payload=resume_payload,
    )
    clean = run_generated_scale_shard(corpus, shard_index=1, shard_count=2)

    assert resumed["status"] == "ok"
    assert resumed["metrics"]["resumed_cases"] == 5
    assert resumed["canonical_summary"] == clean["canonical_summary"]
    assert resumed["checks"]["completed_records_preserved_on_resume"]
    assert {record["recipe_id"] for record in partial["records"]}.issubset(
        {record["recipe_id"] for record in resumed["records"]}
    )


def test_resume_rejects_configuration_drift() -> None:
    corpus = generate_scenario_corpus(count=12, seed=20261103)
    partial = run_generated_scale_shard(corpus, max_new_cases=2)

    with pytest.raises(ValueError, match="resume configuration mismatch"):
        run_generated_scale_shard(
            generate_scenario_corpus(count=12, seed=20261104),
            resume_payload=partial,
        )


def test_merge_keeps_failure_case_unique_and_reports_review() -> None:
    corpus = generate_scenario_corpus(count=16, seed=20261105)
    shards = [
        run_generated_scale_shard(corpus, shard_index=index, shard_count=2)
        for index in range(2)
    ]
    damaged = deepcopy(shards)
    target = damaged[0]["records"][0]
    target["status"] = "review"
    target["checks"]["injected_failure"] = False

    merged = merge_generated_scale_shards(tuple(damaged))

    assert merged["status"] == "review"
    assert merged["failed_recipe_ids"] == (target["recipe_id"],)
    assert merged["checks"]["failure_evidence_is_unique"]


def test_scale_evidence_records_environment_memory_and_round_trips(
    tmp_path: Path,
) -> None:
    corpus = generate_scenario_corpus(count=8, seed=20261106)
    payload = run_generated_scale_shard(corpus, checkpoint_interval=2)

    write_generated_scale_evidence(payload, tmp_path)
    restored = load_generated_scale_resume(tmp_path)

    assert payload["environment"]["dependency_lock_sha256"]
    assert payload["metrics"]["peak_traced_memory_mb"] > 0
    assert payload["metrics"]["final_rss_mb"] > 0
    assert len(payload["checkpoints"]) >= 4
    assert restored["canonical_summary"] == payload["canonical_summary"]
    assert len(tuple((tmp_path / "cases").glob("*.json"))) == 8


def test_generated_simulation_sampling_shards_merge_without_timing_noise() -> None:
    corpus = generate_scenario_corpus(count=12, seed=20261107)
    shards = tuple(
        run_generated_simulation_acceptance(
            corpus,
            tier="smoke",
            sample_size=2,
            seeds=(42,),
            include_operations=False,
            movement_backend_factory=EndpointClearInstantMovementBackend,
            shard_index=index,
            shard_count=2,
        ).as_dict()
        for index in range(2)
    )

    merged = merge_generated_simulation_shards(shards)

    assert merged["status"] == "ok", merged
    assert len(merged["records"]) == 2
    assert merged["checks"]["no_missing_samples"]


def test_generated_simulation_recipe_seed_shards_merge_the_full_case_matrix() -> None:
    corpus = generate_scenario_corpus(count=12, seed=20261108)
    shards = tuple(
        run_generated_simulation_acceptance(
            corpus,
            tier="smoke",
            sample_size=2,
            seeds=(7, 42),
            include_operations=False,
            movement_backend_factory=EndpointClearInstantMovementBackend,
            shard_index=index,
            shard_count=4,
            shard_by_seed=True,
        ).as_dict()
        for index in range(4)
    )

    merged = merge_generated_simulation_shards(shards)

    assert merged["status"] == "ok", merged
    assert len(merged["records"]) == 4
    assert len(merged["sampled_case_ids"]) == 4
    assert merged["checks"]["no_missing_samples"]
    assert not merged["missing_case_ids"]
