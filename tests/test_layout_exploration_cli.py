from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = ROOT / "scripts" / "run_layout_exploration.py"
    spec = importlib.util.spec_from_file_location("layout_exploration_cli_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_layout_exploration_cli_exposes_nightly_scale_soak_without_scale_summary() -> None:
    runner = _load_runner()
    args = runner.build_parser().parse_args(
        ["--suites", "e6", "--skip-e6-scale-summary"]
    )
    assert args.suites == ["e6"]
    assert args.skip_e6_scale_summary is True
    assert args.skip_e6_soak is False


def test_layout_exploration_cli_writes_shared_evidence_contract(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_layout_exploration.py"),
            "--suites",
            "e1",
            "e2",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "ok"
    assert summary["suite_ids"] == ["PM028-E1", "PM028-E2"]
    assert sum(report["case_count"] for report in summary["reports"]) == 291
    assert (tmp_path / "coverage.json").exists()
    assert (tmp_path / "summary.md").exists()

