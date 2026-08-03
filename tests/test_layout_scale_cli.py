from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_cli_shards_merge_and_resume(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    output_json = tmp_path / "report.json"
    output_markdown = tmp_path / "report.md"
    shard_reports = []
    for shard_index in range(2):
        result = _run_layout_cli(
            "--generated-count",
            "12",
            "--shard-index",
            str(shard_index),
            "--shard-count",
            "2",
            "--generated-evidence-dir",
            str(evidence),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        )
        assert result.returncode == 0, result.stderr
        shard_reports.append(
            tmp_path / f"report.shard-{shard_index:03d}-of-002.json"
        )

    merged_json = tmp_path / "merged.json"
    merged_markdown = tmp_path / "merged.md"
    merged = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "merge_layout_acceptance.py"),
            *(str(path) for path in shard_reports),
            "--output-json",
            str(merged_json),
            "--output-markdown",
            str(merged_markdown),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert merged.returncode == 0, merged.stderr
    payload = json.loads(merged_json.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert len(payload["generated_layouts"]["records"]) == 12

    resume_dir = tmp_path / "resume"
    partial = _run_layout_cli(
        "--generated-count",
        "8",
        "--max-generated-cases",
        "2",
        "--generated-evidence-dir",
        str(resume_dir),
        "--output-json",
        str(tmp_path / "partial.json"),
        "--output-markdown",
        str(tmp_path / "partial.md"),
    )
    assert partial.returncode == 1
    resumed = _run_layout_cli(
        "--generated-count",
        "8",
        "--resume-from",
        str(resume_dir),
        "--generated-evidence-dir",
        str(resume_dir),
        "--output-json",
        str(tmp_path / "resumed.json"),
        "--output-markdown",
        str(tmp_path / "resumed.md"),
    )
    assert resumed.returncode == 0, resumed.stderr
    resumed_payload = json.loads((tmp_path / "resumed.json").read_text(encoding="utf-8"))
    assert resumed_payload["generated_layouts"]["metrics"]["resumed_cases"] == 2
    assert len(resumed_payload["generated_layouts"]["records"]) == 8


def _run_layout_cli(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_layout_acceptance.py"),
            "--tier",
            "smoke",
            "--generated-only",
            "--generated-simulation-samples",
            "0",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

