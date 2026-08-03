from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from scripts.run_analysis_comparison_acceptance import run_acceptance


def test_water_barrier_acceptance_generates_replayable_decision_bundle(
    tmp_path: Path,
) -> None:
    manifest = run_acceptance(tmp_path)

    assert manifest["status"] == "pass"
    assert manifest["run_count"] == 6
    assert manifest["bundle_replay_matches"] is True
    assert manifest["wall_seconds"] < 60
    stored = json.loads((tmp_path / "acceptance-manifest.json").read_text("utf-8"))
    assert stored == manifest
    with ZipFile(tmp_path / "comparison-report.zip") as archive:
        assert {
            "baseline.analysis-case.json",
            "candidate.analysis-case.json",
            "comparison-report.json",
            "decision-report.html",
        } == set(archive.namelist())
