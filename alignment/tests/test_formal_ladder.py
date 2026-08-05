from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from metro_alignment.formal_ladder import FormalControlExecution, execute_final_ladder
from metro_alignment.formal_profiles import FormalControlProfile, final_ladder_profile
from metro_alignment.formal_publication import artifact_record

METRO_FINGERPRINT = {"source_tree_sha256": "metro"}
ANALYSIS_FINGERPRINT = {"content_sha256": "analysis"}


def _load_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_acceptance.py"
    spec = importlib.util.spec_from_file_location("formal_ladder_verifier_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_control(control, output: Path) -> FormalControlExecution:
    output.parent.mkdir(parents=True, exist_ok=True)
    canonical = output.with_suffix(".parquet")
    trace = output.with_suffix(".movement_trace.json")
    if control.saturated_flow is None:
        frame = pd.DataFrame(
            [(1, 0.0, 7.0, 18.0)],
            columns=("agent_id", "t_s", "x_m", "y_m"),
        )
    else:
        rows = []
        for agent_id in range(360):
            crossing = 120.25 + agent_id * 179.5 / 360
            rows.extend(
                (
                    (agent_id, crossing - 0.1, 7.0, 18.0),
                    (agent_id, crossing + 0.1, 9.0, 18.0),
                )
            )
        frame = pd.DataFrame(rows, columns=("agent_id", "t_s", "x_m", "y_m"))
    frame.to_parquet(canonical, index=False)
    trace.write_text('{"trace":true}', encoding="utf-8")
    manifest = output.parent / "platform_boarding_simulated.json"
    payload = {
        "schema_version": "alignment_simulation_metrics.v5",
        "scene_id": "platform_boarding",
        "simulation_seed": control.seed,
        "scene_config_sha256": control.sha256,
        "design_sha256": "d" * 64,
        "metro_runtime_fingerprint": METRO_FINGERPRINT,
        "analysis_runtime_fingerprint": ANALYSIS_FINGERPRINT,
        "artifacts": {
            "canonical": artifact_record(
                canonical, record_parent=manifest.parent
            ).model_dump(mode="json"),
            "movement_trace": artifact_record(
                trace, record_parent=manifest.parent
            ).model_dump(mode="json"),
        },
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return FormalControlExecution(
        control=control,
        canonical_path=canonical,
        manifest_path=manifest,
        trace_path=trace,
        scene_config_sha256=control.sha256,
        design_sha256="d" * 64,
        metro_runtime_fingerprint=METRO_FINGERPRINT,
        analysis_runtime_fingerprint=ANALYSIS_FINGERPRINT,
    )


def test_final_ladder_publishes_only_after_all_controls_and_qualifier_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    result = execute_final_ladder(
        profile=final_ladder_profile(),
        output=tmp_path / "platform_boarding_simulated.parquet",
        base_scene_config_sha256="b" * 64,
        design_sha256="d" * 64,
        metro_runtime_fingerprint=METRO_FINGERPRINT,
        analysis_runtime_fingerprint=ANALYSIS_FINGERPRINT,
        run_control=_run_control,
        current_fingerprints=lambda: (METRO_FINGERPRINT, ANALYSIS_FINGERPRINT),
    )
    published = json.loads(active.read_bytes())
    assert published["formal_control_id"] == "mixed-600"
    assert published["runner_provenance"]["trace_replay"] is False
    assert result.ladder_manifest.publication_control_id == "mixed-600"
    assert [item.control_id for item in result.ladder_manifest.controls] == [
        "exit-only-350",
        "entry-only-600",
        "entry-tail-saturated-flow",
        "mixed-600",
    ]
    assert result.ladder_manifest_path.is_file()
    for control in result.ladder_manifest.controls:
        assert len(control.simulation_manifest.path) < 180
    verifier = _load_verifier()
    monkeypatch.setattr(verifier, "scene_config_sha256", lambda scene: "b" * 64)
    monkeypatch.setattr(verifier, "metro_source_fingerprint", lambda: METRO_FINGERPRINT)
    monkeypatch.setattr(
        verifier,
        "analysis_runtime_fingerprint",
        lambda: ANALYSIS_FINGERPRINT,
    )
    evidence = verifier._require_formal_ladder(
        active_manifest=active,
        active_payload=published,
        scene_id="platform_boarding",
        current_design_sha256="d" * 64,
    )
    assert "preregistered saturated-flow qualifier=pass" in evidence


def test_failed_saturated_qualifier_never_switches_active_manifest(tmp_path: Path) -> None:
    active = tmp_path / "platform_boarding_simulated.json"
    active.write_bytes(b'{"old":true}')
    profile = final_ladder_profile()
    qualifier = profile.controls[2]
    assert qualifier.saturated_flow is not None
    failed_registration = replace(
        qualifier.saturated_flow,
        minimum_specific_flow_p_m_s=1.3,
    )
    failed_controls = (*profile.controls[:2], replace(qualifier, saturated_flow=failed_registration), profile.controls[3])
    failed_profile = FormalControlProfile(
        profile.profile_id,
        profile.scene_id,
        failed_controls,
        profile.publication_control_id,
        profile.publication_scope,
    )
    with pytest.raises(RuntimeError, match="saturated-flow gate failed"):
        execute_final_ladder(
            profile=failed_profile,
            output=tmp_path / "platform_boarding_simulated.parquet",
            base_scene_config_sha256="b" * 64,
            design_sha256="d" * 64,
            metro_runtime_fingerprint=METRO_FINGERPRINT,
            analysis_runtime_fingerprint=ANALYSIS_FINGERPRINT,
            run_control=_run_control,
            current_fingerprints=lambda: (METRO_FINGERPRINT, ANALYSIS_FINGERPRINT),
        )
    assert active.read_bytes() == b'{"old":true}'
