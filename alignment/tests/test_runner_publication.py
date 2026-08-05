from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from metro_alignment.metro_executor import AlignmentMesaSimulationExecutor
from metro_alignment.scenes import build_scene_config


def _load_runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_alignment_scene.py"
    spec = importlib.util.spec_from_file_location("alignment_runner_publication_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "old_canonical": tmp_path / "scene_simulated.parquet",
        "old_trace": tmp_path / "scene_simulated.movement_trace.json",
        "manifest": tmp_path / "scene_simulated.json",
        "staged_canonical": tmp_path / ".canonical.staging.parquet",
        "staged_trace": tmp_path / ".trace.staging.json",
        "canonical": tmp_path / "scene_simulated.sha256-new.parquet",
        "trace": tmp_path / "scene_simulated.sha256-new.movement_trace.json",
    }
    paths["old_canonical"].write_bytes(b"old canonical")
    paths["old_trace"].write_bytes(b"old trace")
    paths["manifest"].write_text('{"old": true}', encoding="utf-8")
    paths["staged_canonical"].write_bytes(b"new canonical")
    paths["staged_trace"].write_bytes(b"new trace")
    return paths


def test_runner_seed_default_defers_to_scene_registry(monkeypatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_alignment_scene.py",
            "--scene-id",
            "platform_boarding",
            "--output",
            "unused.parquet",
        ],
    )
    assert runner.parse_args().seed is None


def test_runner_parses_only_registered_formal_profiles(monkeypatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_alignment_scene.py",
            "--scene-id",
            "platform_boarding",
            "--output",
            "unused.parquet",
            "--profile",
            "alignment_step5_final.v1",
        ],
    )
    assert runner.parse_args().profile == "alignment_step5_final.v1"


def test_formal_control_config_uses_only_preregistered_demand_and_horizon() -> None:
    runner = _load_runner()
    base = build_scene_config("platform_boarding")
    control = runner.final_ladder_profile().controls[0]
    config = runner._formal_control_config(base, control)
    assert config.entry_count_hour == 0
    assert config.exit_count_hour == 4404
    assert config.minutes == 6
    assert control.horizon_steps == 350


def test_formal_output_staging_names_fit_nested_windows_paths() -> None:
    runner = _load_runner()
    output = Path("ladder") / ("r" * 32) / "02-entry-tail-saturated-flow" / "run.parquet"
    staged_canonical, staged_trace = runner._staged_output_paths(output, "f" * 32)

    assert len(staged_canonical.name) < 64
    assert len(staged_trace.name) < 64


def test_formal_runner_uses_alignment_compatibility_executor(monkeypatch) -> None:
    runner = _load_runner()
    captured = {}

    def fake_run_simulation(request, executor):
        captured["executor"] = executor
        return SimpleNamespace(
            frames=[],
            runtime=SimpleNamespace(
                movement_backend=SimpleNamespace(movement_trace=lambda: {"points": []}),
                alignment_source_admission_metrics=dict,
                scenario=SimpleNamespace(
                    entry_groups=417,
                    exit_groups=367,
                    group_size=1,
                    initial_train_offset_seconds=75.0,
                    train_headway_seconds=240.0,
                    train_dwell_seconds=35.0,
                    tick_seconds=1,
                    demand_steps=600,
                    horizon_steps=600,
                ),
            ),
        )

    monkeypatch.setattr(runner, "run_simulation", fake_run_simulation)
    monkeypatch.setattr(runner, "_require_admission_acceptance", lambda *args, **kwargs: None)

    runner._run_simulation(build_scene_config("platform_boarding"))

    assert type(captured["executor"]) is AlignmentMesaSimulationExecutor


def _accepted_admission_metrics() -> dict:
    return {
        "spawned_entry_persons": 417,
        "spawned_exit_persons": 367,
        "alignment_scheduled_entry_persons": 417,
        "alignment_scheduled_source_persons": 417,
        "alignment_requested_due_source_persons": 417,
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
        "departed_trains": 3,
        "alignment_entry_demand_conserved": True,
        "alignment_source_demand_conserved": True,
    }


def test_formal_runner_accepts_conserved_source_admission() -> None:
    runner = _load_runner()

    runner._require_admission_acceptance(
        _accepted_admission_metrics(),
        expected_entry_persons=417,
        expected_exit_persons=367,
        expected_departed_trains=3,
    )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("spawned_entry_persons", 416),
        ("spawned_exit_persons", 366),
        ("pending_alighting_persons", 1),
        ("alignment_pending_source_groups", 1),
        ("alignment_entry_dropped_persons", 1),
        ("alignment_source_demand_conserved", False),
        ("jupedsim_missing_agents", 1),
        ("jupedsim_degraded_holds", 1),
    ],
)
def test_formal_runner_rejects_admission_or_native_body_failures(
    field: str,
    bad_value,
) -> None:
    runner = _load_runner()
    metrics = _accepted_admission_metrics()
    metrics[field] = bad_value

    with pytest.raises(RuntimeError, match=field):
        runner._require_admission_acceptance(
            metrics,
            expected_entry_persons=417,
            expected_exit_persons=367,
            expected_departed_trains=3,
        )


def test_trace_replay_cannot_bypass_admission_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    config = build_scene_config("platform_boarding")
    _, design_sha256 = runner.build_metro_scenario(config)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text('{"points": []}', encoding="utf-8")
    metrics = _accepted_admission_metrics()
    metrics["alignment_pending_source_groups"] = 1
    manifest = {
        "schema_version": runner.SIMULATED_ARTIFACT_SCHEMA_VERSION,
        "scene_id": config.scene_id,
        "simulation_seed": config.seed,
        "scene_config_schema_version": runner.SCENE_CONFIG_SCHEMA_VERSION,
        "scene_config": runner.scene_config_payload(config),
        "scene_config_sha256": runner.scene_config_sha256(config),
        "design_sha256": design_sha256,
        "metro_runtime_fingerprint": {"stable": True},
        "final_frame_metrics": metrics,
        "artifacts": {
            "movement_trace": {
                "path": trace_path.name,
                "sha256": _sha256(trace_path),
                "size_bytes": trace_path.stat().st_size,
            }
        },
    }
    (tmp_path / "platform_boarding_simulated.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "metro_source_fingerprint", lambda: {"stable": True})
    monkeypatch.setattr(
        runner,
        "alignment_source_geometry_preflight",
        lambda scenario: {"status": "pass"},
    )

    with pytest.raises(RuntimeError, match="alignment_pending_source_groups"):
        runner._load_verified_trace_replay(
            output=tmp_path / "platform_boarding_simulated.parquet",
            config=config,
        )


def test_trace_replay_cannot_bypass_source_geometry_preflight(tmp_path: Path) -> None:
    runner = _load_runner()
    invalid_config = replace(
        build_scene_config("platform_boarding"),
        alighting_source_lateral_offset_m=0.0,
    )

    with pytest.raises(runner.AlignmentSourceGeometryConflict):
        runner._load_verified_trace_replay(
            output=tmp_path / "platform_boarding_simulated.parquet",
            config=invalid_config,
        )


def test_source_preflight_blocker_is_persisted_as_fail_closed_evidence(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config = build_scene_config("platform_boarding")
    report = {
        "schema_version": "alignment_source_geometry_preflight.v3",
        "runtime_status": "not_started",
        "scientific_status": "source_geometry_conflict",
        "outcome": "model_invalid",
        "status": "fail",
        "capacity_certificate": True,
        "compiler_error_codes": ["capacity.coactive_slot_conflict"],
        "compiler_rejection_reproduced": True,
        "queue_reports": [{"queue_id": "queue-a", "status": "conflict"}],
        "blockers": [
            {
                "queue_id": "queue-a",
                "blockers": [
                    "boarding_holding_area_overlaps_alighting_source_lattice"
                ],
            }
        ],
    }

    path = runner._write_source_preflight_blocker(
        output=tmp_path / "platform_boarding_simulated.parquet",
        config=config,
        report=report,
    )

    artifact = json.loads(path.read_bytes())
    assert artifact["schema_version"] == "alignment_source_preflight_artifact.v2"
    assert artifact["runtime_status"] == "not_started"
    assert artifact["scientific_status"] == "model_invalid"
    assert artifact["blocker"] == "alighting_source_geometry_conflict"
    assert artifact["release_eligible"] is False
    assert artifact["preflight"] == report


def test_passed_source_preflight_is_persisted_with_current_scene_contract(
    tmp_path: Path,
) -> None:
    runner = _load_runner()
    config = build_scene_config("platform_boarding")
    report = {
        "schema_version": "alignment_source_geometry_preflight.v3",
        "runtime_status": "ready",
        "scientific_status": "eligible",
        "outcome": "eligible",
        "status": "pass",
        "capacity_certificate": True,
        "compiler_error_codes": [],
        "compiler_rejection_reproduced": False,
        "queue_reports": [{"queue_id": "queue-a", "status": "pass"}],
        "blockers": [],
    }

    path = runner._write_source_preflight_artifact(
        output=tmp_path / "platform_boarding_simulated.parquet",
        config=config,
        report=report,
    )

    artifact = json.loads(path.read_bytes())
    assert artifact["schema_version"] == "alignment_source_preflight_artifact.v2"
    assert artifact["scene_config"]["alighting_source_lateral_offset_m"] == 10.0
    assert artifact["runtime_status"] == "ready"
    assert artifact["scientific_status"] == "eligible"
    assert artifact["blocker"] is None
    assert artifact["release_eligible"] is False


def test_successful_bundle_can_retire_a_superseded_source_blocker(tmp_path: Path) -> None:
    runner = _load_runner()
    config = build_scene_config("platform_boarding")
    blocker = tmp_path / "platform_boarding_source_preflight.json"
    blocker.write_text('{"preflight":{"status":"fail"}}', encoding="utf-8")

    runner._retire_source_preflight_blocker(
        output=tmp_path / "platform_boarding_simulated.parquet",
        config=config,
    )

    assert not blocker.exists()


def test_minutes_override_can_only_shorten_the_registered_scene() -> None:
    runner = _load_runner()
    config = build_scene_config("platform_boarding")

    shortened = runner._apply_cli_overrides(config, seed=None, minutes=4)
    assert shortened.minutes == 4
    assert shortened.demand_minutes == 4
    with pytest.raises(ValueError, match="smoke-run upper bound"):
        runner._apply_cli_overrides(config, seed=None, minutes=14)


@pytest.mark.parametrize(
    "failure_point", ["canonical", "trace", "pre_manifest", "post_manifest"]
)
def test_bundle_publication_failure_preserves_previous_formal_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    runner = _load_runner()
    paths = _fixture_paths(tmp_path)
    old_hashes = {
        name: _sha256(paths[name]) for name in ("old_canonical", "old_trace", "manifest")
    }
    real_replace = os.replace

    if failure_point in {"canonical", "trace"}:
        failing_source = paths[f"staged_{failure_point}"]

        def replace_with_failure(source, destination):
            if Path(source) == failing_source:
                raise OSError(f"injected {failure_point} promotion failure")
            return real_replace(source, destination)

        monkeypatch.setattr(runner.os, "replace", replace_with_failure)
        monkeypatch.setattr(runner, "_runtime_fingerprints_match", lambda *_: True)
    else:
        answers = iter([True, failure_point != "pre_manifest", False])
        monkeypatch.setattr(
            runner, "_runtime_fingerprints_match", lambda *_: next(answers)
        )

    with pytest.raises((OSError, RuntimeError)):
        runner._publish_staged_bundle(
            staged_canonical=paths["staged_canonical"],
            staged_trace=paths["staged_trace"],
            canonical_path=paths["canonical"],
            trace_path=paths["trace"],
            manifest_path=paths["manifest"],
            payload={"schema_version": "test"},
            expected_metro_fingerprint={"metro": "stable"},
            expected_analysis_fingerprint={"analysis": "stable"},
        )

    assert {
        name: _sha256(paths[name]) for name in ("old_canonical", "old_trace", "manifest")
    } == old_hashes
    assert not paths["canonical"].exists()
    assert not paths["trace"].exists()


def test_bundle_publication_switches_only_manifest_to_immutable_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    paths = _fixture_paths(tmp_path)
    old_canonical_hash = _sha256(paths["old_canonical"])
    old_trace_hash = _sha256(paths["old_trace"])
    monkeypatch.setattr(runner, "_runtime_fingerprints_match", lambda *_: True)

    runner._publish_staged_bundle(
        staged_canonical=paths["staged_canonical"],
        staged_trace=paths["staged_trace"],
        canonical_path=paths["canonical"],
        trace_path=paths["trace"],
        manifest_path=paths["manifest"],
        payload={"schema_version": "test"},
        expected_metro_fingerprint={"metro": "stable"},
        expected_analysis_fingerprint={"analysis": "stable"},
    )

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["artifacts"]["canonical"]["path"] == paths["canonical"].name
    assert manifest["artifacts"]["movement_trace"]["path"] == paths["trace"].name
    assert _sha256(paths["old_canonical"]) == old_canonical_hash
    assert _sha256(paths["old_trace"]) == old_trace_hash


def test_bundle_publication_supports_fresh_nested_ladder_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    parent = tmp_path / "ladder" / ("r" * 32) / "00-exit-only-350"
    parent.mkdir(parents=True)
    staged_canonical = parent / ".c.parquet"
    staged_trace = parent / ".t.json"
    staged_canonical.write_bytes(b"canonical")
    staged_trace.write_bytes(b"trace")
    canonical = parent / "platform_boarding_simulated.sha256-new.parquet"
    trace = parent / "platform_boarding_simulated.sha256-new.movement_trace.json"
    manifest = parent / "platform_boarding_simulated.json"
    monkeypatch.setattr(runner, "_runtime_fingerprints_match", lambda *_: True)

    runner._publish_staged_bundle(
        staged_canonical=staged_canonical,
        staged_trace=staged_trace,
        canonical_path=canonical,
        trace_path=trace,
        manifest_path=manifest,
        payload={"schema_version": "test"},
        expected_metro_fingerprint={"metro": "stable"},
        expected_analysis_fingerprint={"analysis": "stable"},
    )

    assert manifest.exists()
    assert canonical.exists()
    assert trace.exists()
    assert not tuple(parent.glob(".*.staging*"))
