from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from metro_alignment import scenes as scene_registry
from metro_alignment.datasets.registry import get_dataset_spec, list_dataset_specs
from metro_alignment.scenes import build_scene_config


def _load_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_acceptance.py"
    spec = importlib.util.spec_from_file_location("alignment_verify_acceptance_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"alignment_{path.stem}_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_acceptance_enumerates_every_active_dataset(monkeypatch) -> None:
    verifier = _load_verifier()
    missing = replace(get_dataset_spec("eindhoven_platform_v1"), dataset_id="missing_active")
    canonical_visits: list[str] = []
    observed_visits: list[str] = []
    monkeypatch.setattr(
        verifier,
        "list_dataset_specs",
        lambda: (*list_dataset_specs(), missing),
    )
    monkeypatch.setattr(
        verifier,
        "_check_canonical",
        lambda dataset_id: (canonical_visits.append(dataset_id) or [], []),
    )
    monkeypatch.setattr(
        verifier,
        "_check_observed",
        lambda dataset_id: (observed_visits.append(dataset_id) or [], []),
    )
    assert verifier._step3().status == "pass"
    assert verifier._step4().status == "pass"
    expected = ["eindhoven_platform_v1", "missing_active"]
    assert canonical_visits == expected
    assert observed_visits == expected


def test_observed_cli_sampling_defaults_defer_to_dataset_registry(monkeypatch) -> None:
    script = _load_script("compute_observed_metrics.py")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compute_observed_metrics.py",
            "--dataset-id",
            "eindhoven_platform_v1",
            "--input",
            "unused.parquet",
        ],
    )
    args = script.parse_args()
    assert args.max_rows is None
    assert args.sample_windows is None


def test_json_loaders_reject_non_object_roots(tmp_path) -> None:
    verifier = _load_verifier()
    path = tmp_path / "artifact.json"
    for content in ("[]", "null", "42", '"text"'):
        path.write_text(content, encoding="utf-8")
        try:
            verifier._load_json(path)
        except TypeError as exc:
            assert "root must be an object" in str(exc)
        else:
            raise AssertionError(f"accepted non-object JSON root: {content}")


def _valid_source_preflight_artifact() -> dict:
    return {
        "runtime_status": "not_started",
        "scientific_status": "model_invalid",
        "blocker": "alighting_source_geometry_conflict",
        "release_eligible": False,
        "preflight": {
            "schema_version": "alignment_source_geometry_preflight.v3",
            "runtime_status": "not_started",
            "scientific_status": "source_geometry_conflict",
            "outcome": "model_invalid",
            "status": "fail",
            "capacity_certificate": True,
            "compiler_error_codes": ["capacity.coactive_slot_conflict"],
            "compiler_rejection_reproduced": True,
            "queue_reports": [{"queue_id": "queue-a", "status": "conflict"}],
            "blockers": [{"queue_id": "queue-a", "blockers": ["overlap"]}],
        },
    }


def _valid_passed_source_preflight_artifact() -> dict:
    return {
        "runtime_status": "ready",
        "scientific_status": "eligible",
        "blocker": None,
        "release_eligible": False,
        "preflight": {
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
        },
    }


@pytest.mark.parametrize(
    ("path", "bad_value"),
    [
        (("scientific_status",), "capacity_exceeded"),
        (("release_eligible",), True),
        (("preflight", "schema_version"), "alignment_source_geometry_preflight.v1"),
        (("preflight", "outcome"), "capacity_exceeded"),
        (("preflight", "capacity_certificate"), False),
        (("preflight", "blockers"), []),
    ],
)
def test_source_preflight_semantics_fail_closed(path, bad_value) -> None:
    verifier = _load_verifier()
    artifact = deepcopy(_valid_source_preflight_artifact())
    target = artifact
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="source preflight"):
        verifier._require_source_preflight_semantics(artifact)


def test_source_preflight_semantics_accept_current_pass_state() -> None:
    verifier = _load_verifier()

    report = verifier._require_source_preflight_semantics(
        _valid_passed_source_preflight_artifact()
    )

    assert report["status"] == "pass"


def test_nested_wrong_shapes_become_structured_blockers(monkeypatch) -> None:
    verifier = _load_verifier()
    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False
        if path.name.endswith("_source_preflight.json")
        else real_exists(path),
    )
    monkeypatch.setattr(
        verifier,
        "_load_json",
        lambda path: {
            "schema_version": "alignment_observed_metrics.v5",
            "dataset_id": "eindhoven_platform_v1",
            "canonical_schema_version": verifier.CANONICAL_SCHEMA_VERSION,
            "metric_schema_version": verifier.METRIC_SCHEMA_VERSION,
            "metrics": [],
            "metadata": [],
            "input_artifacts": [],
        },
    )
    monkeypatch.setattr(verifier, "read_canonical", lambda path: pd.DataFrame())
    monkeypatch.setattr(verifier, "compute_observed_evidence", lambda *args, **kwargs: ({}, {}))
    _, blockers = verifier._check_observed("eindhoven_platform_v1")
    assert any("metrics must be an object" in blocker for blocker in blockers)
    assert any("metadata must be an object" in blocker for blocker in blockers)

    monkeypatch.setattr(
        verifier,
        "_load_json",
        lambda path: {
            "schema_version": "alignment_simulation_metrics.v5",
            "canonical_schema_version": verifier.CANONICAL_SCHEMA_VERSION,
            "metric_schema_version": verifier.METRIC_SCHEMA_VERSION,
            "scene_config_schema_version": verifier.SCENE_CONFIG_SCHEMA_VERSION,
            "metrics": [],
            "trace_provenance": [],
            "scene_config": [],
            "artifacts": [],
        },
    )
    _, blockers = verifier._check_simulation("platform_boarding")
    assert any("metrics must be an object" in blocker for blocker in blockers)
    assert any("trace_provenance must be an object" in blocker for blocker in blockers)
    assert any("artifacts must be an object" in blocker for blocker in blockers)


def test_acceptance_enumerates_every_ready_scene(monkeypatch) -> None:
    verifier = _load_verifier()
    missing = replace(build_scene_config("platform_boarding"), scene_id="missing_ready")
    monkeypatch.setitem(scene_registry.SCENE_FACTORIES, "missing_ready", lambda: missing)
    assert verifier._step5().status == "fail"
    assert verifier._step6().status == "fail"
    assert verifier._step7().status in {"fail", "pending"}


def test_acceptance_rejects_an_empty_ready_scene_set(monkeypatch) -> None:
    verifier = _load_verifier()
    pending = build_scene_config("bottleneck")
    monkeypatch.setattr(verifier, "list_scene_configs", lambda: ((pending.scene_id, pending),))
    assert verifier._step5().status == "fail"
    assert verifier._step6().status == "fail"
    assert verifier._step7().status == "fail"


def test_acceptance_structures_dataset_registry_errors(monkeypatch) -> None:
    verifier = _load_verifier()

    def invalid_registry():
        raise ValueError("key/id mismatch")

    monkeypatch.setattr(verifier, "list_dataset_specs", invalid_registry)
    assert verifier._step2(test_ok=True).status == "fail"
    assert verifier._step3().status == "fail"
    assert verifier._step4().status == "fail"


def test_release_status_requires_report_parameter_authorization() -> None:
    verifier = _load_verifier()
    steps = [
        verifier.StepResult(
            step=index,
            name=f"step-{index}",
            status="pass",
            evidence=[],
            blockers=[],
            release_authorized=False if index == 7 else None,
        )
        for index in range(1, 9)
    ]
    assert verifier._aggregate_statuses(steps) == ("pass", "hold")
    steps[6] = verifier.StepResult(
        step=7,
        name="step-7",
        status="pass",
        evidence=[],
        blockers=[],
        release_authorized=True,
    )
    assert verifier._aggregate_statuses(steps) == ("pass", "pass")
