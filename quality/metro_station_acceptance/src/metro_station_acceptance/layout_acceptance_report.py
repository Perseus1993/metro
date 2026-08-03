"""Acceptance harness migrated from the production runtime namespace."""

from __future__ import annotations

from .layout_acceptance import CrossLayoutAcceptanceReport, LayoutMaturityReport


def render_layout_acceptance_markdown(
    report: CrossLayoutAcceptanceReport,
) -> str:
    lines = [
        "# Cross-layout maturity acceptance",
        "",
        f"- Tier: `{report.tier}`",
        f"- Seeds: `{', '.join(str(seed) for seed in report.seeds)}`",
        f"- Status: **{report.status.upper()}**",
        "",
        "| Layout | Contract | Journeys | Operations | Clearance | Determinism | Status |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_layout_row(item) for item in report.layouts)
    failures = _failures(report)
    lines.extend(["", "## Blocking checks", ""])
    if failures:
        lines.extend(f"- `{failure}`" for failure in failures)
    else:
        lines.append("- None")
    lines.extend(["", "## Evidence counts", ""])
    for item in report.layouts:
        normal_runs = len(item.journeys.normal)
        evacuation_runs = len(item.journeys.evacuation)
        operational_runs = len(item.operations.reports)
        trajectories = sum(
            run.trajectory_count
            for run in (*item.journeys.normal, *item.journeys.evacuation)
        )
        lines.append(
            f"- `{item.layout_id}`: {normal_runs} normal, "
            f"{evacuation_runs} evacuation, {operational_runs} operational, "
            f"{trajectories} journey trajectories"
        )
    return "\n".join(lines) + "\n"


def _layout_row(report: LayoutMaturityReport) -> str:
    return "| {layout} | {contract} | {journeys} | {operations} | {clearance} | {determinism} | {status} |".format(
        layout=report.layout_id,
        contract=report.contract.status,
        journeys=report.journeys.status,
        operations=report.operations.status,
        clearance=_yes_no(report.checks["strict_clearance_all_runs"]),
        determinism=_yes_no(report.checks["deterministic_replay"]),
        status=report.status,
    )


def _failures(report: CrossLayoutAcceptanceReport) -> list[str]:
    failures = [name for name, passed in report.checks.items() if not passed]
    for layout in report.layouts:
        failures.extend(
            f"{layout.layout_id}.{name}"
            for name, passed in layout.checks.items()
            if not passed
        )
        failures.extend(
            f"{layout.layout_id}.contract.{name}"
            for name, passed in layout.contract.checks.items()
            if not passed
        )
    return failures


def _yes_no(value: bool) -> str:
    return "pass" if value else "fail"
