from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .layout_exploration_result import ExplorationSuiteReport


def write_exploration_evidence(
    reports: tuple[ExplorationSuiteReport, ...],
    output_dir: Path,
    *,
    run_metadata: Mapping[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "layout_exploration_run.v1",
        "status": "ok" if reports and all(report.status == "ok" for report in reports) else "review",
        "suite_ids": [report.suite_id for report in reports],
        "reports": [report.as_dict() for report in reports],
        "metadata": dict(run_metadata or {}),
    }
    _write_json(output_dir / "summary.json", payload)
    _write_json(
        output_dir / "coverage.json",
        {report.suite_id: report.coverage for report in reports},
    )
    (output_dir / "summary.md").write_text(
        render_exploration_markdown(reports),
        encoding="utf-8",
    )
    for report in reports:
        case_dir = output_dir / "cases" / report.suite_id
        case_dir.mkdir(parents=True, exist_ok=True)
        for result in report.results:
            _write_json(case_dir / f"{result.case.case_id}.json", result.as_dict())
            if result.status != "ok":
                failure_dir = output_dir / "failures" / result.case.case_id
                failure_dir.mkdir(parents=True, exist_ok=True)
                _write_json(failure_dir / "result.json", result.as_dict())


def render_exploration_markdown(reports: tuple[ExplorationSuiteReport, ...]) -> str:
    lines = [
        "# Layout exploration acceptance",
        "",
        "| Suite | Cases | Failed | Status |",
        "|---|---:|---:|---:|",
    ]
    for report in reports:
        lines.append(
            f"| {report.suite_id} | {len(report.results)} | "
            f"{len(report.failed_case_ids)} | {report.status} |"
        )
    lines.extend(["", "## Blocking cases", ""])
    failures = [
        f"{report.suite_id}.{case_id}"
        for report in reports
        for case_id in report.failed_case_ids
    ]
    lines.extend(f"- `{failure}`" for failure in failures)
    if not failures:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

