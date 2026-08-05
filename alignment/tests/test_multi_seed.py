from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from metro_alignment.metrics.fundamental import WALKING_SPEED_PROXY_KEY
from metro_alignment.multi_seed import (
    REQUIRED_SEEDS,
    aggregate_formal_manifests,
    aggregate_legacy_smoke,
    confidence_interval_95,
)


def _final_metrics() -> dict:
    return {
        "pending_alighting_persons": 0,
        "alignment_pending_source_groups": 0,
        "alignment_pending_source_persons": 0,
        "alignment_pending_entry_groups": 0,
        "alignment_pending_entry_persons": 0,
        "alignment_entry_dropped_persons": 0,
        "alignment_source_dropped_persons": 0,
        "jupedsim_missing_agents": 0,
        "jupedsim_degraded_holds": 0,
        "alignment_active_boardings": 0,
        "alignment_reserved_boarding_persons": 0,
        "alignment_entry_demand_conserved": True,
        "alignment_source_demand_conserved": True,
        "alignment_requested_due_source_persons": 100,
        "alignment_scheduled_source_persons": 100,
        "spawned_entry_persons": 120,
        "alignment_scheduled_entry_persons": 120,
        "spawned_exit_persons": 100,
        "departed_trains": 3,
    }


def _write_formal(path: Path, seed: int, value: float) -> None:
    artifact_records = {}
    for key, suffix, content in (
        ("canonical", ".parquet", f"canonical-{seed}".encode()),
        ("movement_trace", ".movement_trace.json", f"trace-{seed}".encode()),
    ):
        sha256 = hashlib.sha256(content).hexdigest()
        artifact = path.parent / f"seed-{seed}.sha256-{sha256}{suffix}"
        artifact.write_bytes(content)
        artifact_records[key] = {
            "path": artifact.name,
            "sha256": sha256,
            "size_bytes": len(content),
        }
    payload = {
        "schema_version": "alignment_simulation_metrics.v5",
        "scene_id": "platform_boarding",
        "simulation_seed": seed,
        "canonical_schema_version": "alignment_trajectory.v1",
        "metric_schema_version": "alignment_metrics.v5",
        "scene_config_schema_version": "alignment_scene_config.v1",
        "scene_config": {"scene_id": "platform_boarding", "minutes": 10, "seed": seed},
        "design_sha256": "design",
        "metro_runtime_fingerprint": {"source_tree_sha256": "metro"},
        "analysis_runtime_fingerprint": {"content_sha256": "analysis"},
        "metrics": {
            WALKING_SPEED_PROXY_KEY: {"p50": value},
            "metric_support": {
                WALKING_SPEED_PROXY_KEY: {"seed_n": 1, "seed_values": [seed]}
            },
        },
        "final_frame_metrics": _final_metrics(),
        "artifacts": artifact_records,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_formal_fixed_seed_aggregate_converges(tmp_path: Path) -> None:
    paths = []
    for offset, seed in enumerate(REQUIRED_SEEDS):
        path = tmp_path / f"seed-{seed}_simulated.json"
        _write_formal(path, seed, 1.0 + (offset - 4.5) * 0.002)
        paths.append(path)
    result = aggregate_formal_manifests(paths)
    assert result["seed_n"] == 10
    assert result["converged"] is True
    assert result["uncertainty"]["relative_half_width"] <= 0.05
    assert [run["seed"] for run in result["runs"]] == list(REQUIRED_SEEDS)


def test_ci_rejects_wide_half_width() -> None:
    interval = confidence_interval_95([0.5, 1.5] * 5)
    assert interval["numerically_converged"] is False


def test_formal_aggregate_rejects_missing_seed(tmp_path: Path) -> None:
    paths = []
    for seed in REQUIRED_SEEDS[:-1]:
        path = tmp_path / f"seed-{seed}_simulated.json"
        _write_formal(path, seed, 1.0)
        paths.append(path)
    with pytest.raises(ValueError, match="fixed seed set"):
        aggregate_formal_manifests(paths)


def test_formal_aggregate_rejects_failed_step5(tmp_path: Path) -> None:
    paths = []
    for seed in REQUIRED_SEEDS:
        path = tmp_path / f"seed-{seed}_simulated.json"
        _write_formal(path, seed, 1.0)
        paths.append(path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["final_frame_metrics"]["jupedsim_missing_agents"] = 1
    paths[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="Step 5 final metrics failed"):
        aggregate_formal_manifests(paths)


def test_legacy_smoke_never_becomes_convergence_evidence(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "alignment_simulation_metrics.v2",
                "metrics": {"free_flow_speed_m_s": {"p50": 0.91}},
            }
        ),
        encoding="utf-8",
    )
    result = aggregate_legacy_smoke(legacy)
    assert result["uncertainty"]["numerically_converged"] is True
    assert result["converged"] is False
    assert result["gate_status"] == "smoke_only"
    assert result["release_eligible_for_multi_seed_gate"] is False
