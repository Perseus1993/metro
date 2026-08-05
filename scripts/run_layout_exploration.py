from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.boundary_trial_acceptance import (  # noqa: E402
    run_boundary_trial_acceptance,
)
from metro_station_acceptance.demand_fault_acceptance import (  # noqa: E402
    run_demand_fault_acceptance,
)
from metro_station_acceptance.generated_scale_acceptance import (  # noqa: E402
    scale_environment_manifest,
)
from metro_station_acceptance.layout_exploration_evidence import (  # noqa: E402
    write_exploration_evidence,
)
from metro_station_acceptance.layout_exploration_result import (  # noqa: E402
    ExplorationCaseResult,
    ExplorationStageResult,
    ExplorationSuiteReport,
)
from metro_station_acceptance.metamorphic_acceptance import (  # noqa: E402
    run_metamorphic_acceptance,
)
from metro_station_acceptance.replay_browser_acceptance import (  # noqa: E402
    run_replay_browser_acceptance,
)
from metro_station_acceptance.scale_soak_acceptance import (  # noqa: E402
    run_scale_soak_acceptance,
)
from metro_station_acceptance.topology_trial_acceptance import (  # noqa: E402
    run_topology_trial_acceptance,
)
from metro_station_testkit.demand_fault_catalog import (  # noqa: E402
    FAULT_PROFILES,
    demand_fault_cases,
)
from metro_station_testkit.layout_exploration_case import (  # noqa: E402
    LayoutExplorationCase,
)


SUITES = ("e1", "e2", "e3", "e4", "e5", "e6")
DEFAULT_OUTPUT = ROOT / "output" / "layout_exploration" / "pm028"
DEFAULT_E6_SCALE_REPORT = (
    ROOT / "output" / "layout_exploration" / "pm028-e6-smoke-v2" / "report.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run PM-028 topology/layout exploration suites with one evidence contract."
    )
    parser.add_argument("--suites", nargs="+", choices=SUITES, default=list(SUITES))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--e3-mode",
        choices=("full", "representative"),
        default="full",
    )
    parser.add_argument(
        "--e6-scale-report",
        type=Path,
        default=DEFAULT_E6_SCALE_REPORT,
        help="completed generated smoke/nightly/release report to include in E6 evidence",
    )
    parser.add_argument("--skip-e6-soak", action="store_true")
    parser.add_argument(
        "--skip-e6-scale-summary",
        action="store_true",
        help="run the preregistered scale-soak workload without requiring a scale report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = tuple(dict.fromkeys(args.suites))
    reports: list[ExplorationSuiteReport] = []
    for suite in selected:
        if suite == "e1":
            reports.append(run_topology_trial_acceptance())
        elif suite == "e2":
            reports.append(run_boundary_trial_acceptance())
        elif suite == "e3":
            cases = None if args.e3_mode == "full" else _representative_e3_cases()
            reports.append(run_demand_fault_acceptance(cases))
        elif suite == "e4":
            reports.append(run_metamorphic_acceptance())
        elif suite == "e5":
            reports.append(
                run_replay_browser_acceptance(args.output_dir / "e5_browser")
            )
        elif suite == "e6":
            if not args.skip_e6_scale_summary:
                reports.append(_scale_report_summary(args.e6_scale_report))
            if not args.skip_e6_soak:
                reports.append(run_scale_soak_acceptance())
    write_exploration_evidence(
        tuple(reports),
        args.output_dir,
        run_metadata={
            "objective": "PM-028 layout/topology exploration",
            "selected_suites": selected,
            "e3_mode": args.e3_mode,
            "environment": scale_environment_manifest(ROOT),
        },
    )
    status = "ok" if reports and all(report.status == "ok" for report in reports) else "review"
    print(
        json.dumps(
            {
                "status": status,
                "suites": {
                    report.suite_id: {
                        "status": report.status,
                        "cases": len(report.results),
                        "failed": len(report.failed_case_ids),
                    }
                    for report in reports
                },
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if status == "ok" else 1


def _representative_e3_cases():
    wanted = {"BASELINE", *FAULT_PROFILES}
    return tuple(
        case
        for case in demand_fault_cases()
        if case.seed == 41
        and case.factors["topology"] == "TB4"
        and case.factors["demand"] == "D2-COUNTER"
        and case.factors["fault"] in wanted
    )


def _scale_report_summary(path: Path) -> ExplorationSuiteReport:
    if not path.exists():
        raise FileNotFoundError(f"E6 scale report does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    static = payload.get("generated_layouts") or {}
    simulation = payload.get("generated_simulation") or {}
    static_case = LayoutExplorationCase(
        suite_id="PM028-E6-SCALE",
        case_id="E6-SCALE-STATIC",
        generator_version=str(static.get("config", {}).get("generator_version", "unknown")),
        expected_class="STRESS",
        factors={
            "tier": payload.get("tier"),
            "case_count": static.get("metrics", {}).get("completed_cases", 0),
        },
        requirements=("PM-028", "PM-028-E6"),
    )
    simulation_case = LayoutExplorationCase(
        suite_id="PM028-E6-SCALE",
        case_id="E6-SCALE-SIMULATION",
        generator_version=str(static.get("config", {}).get("generator_version", "unknown")),
        expected_class="STRESS",
        factors={
            "tier": payload.get("tier"),
            "sample_count": len(simulation.get("records", ())),
            "seeds": simulation.get("seeds", ()),
        },
        requirements=("PM-028", "PM-028-E6"),
    )
    static_ok = static.get("status") == "ok"
    simulation_ok = simulation.get("status") == "ok"
    static_result = ExplorationCaseResult(
        static_case,
        "pass" if static_ok else "review",
        (
            ExplorationStageResult(
                "scale_static",
                "ok" if static_ok else "review",
                checks={"static_scale_report_ok": static_ok},
                metrics=static.get("metrics", {}),
            ),
        ),
        {"static_scale_report_ok": static_ok},
        artifacts={"source_report": str(path)},
    )
    simulation_result = ExplorationCaseResult(
        simulation_case,
        "pass" if simulation_ok else "review",
        (
            ExplorationStageResult(
                "scale_simulation",
                "ok" if simulation_ok else "review",
                checks={"simulation_scale_report_ok": simulation_ok},
                metrics={
                    "sample_count": len(simulation.get("records", ())),
                    "seeds": simulation.get("seeds", ()),
                },
            ),
        ),
        {"simulation_scale_report_ok": simulation_ok},
        artifacts={"source_report": str(path)},
    )
    coverage = static.get("config", {}).get("coverage", {})
    checks = {
        "static_scale_report_ok": static_ok,
        "simulation_scale_report_ok": simulation_ok,
        "topology_factors_covered": set(
            coverage.get("dimensions", {}).get("vertical_topology", {})
        )
        == {"FULL", "CHAIN", "DUAL_CLUSTER"},
        "fare_factors_covered": set(
            coverage.get("dimensions", {}).get("fare_topology", {})
        )
        == {"BIDIRECTIONAL", "SPLIT_ENTRY_EXIT"},
        "five_footprints_covered": set(
            coverage.get("dimensions", {}).get("topology_footprint", {})
        )
        == {"RECT", "L", "T", "NECK", "U"},
        "dirty_worktree_disclosed": "git_dirty" in static.get("environment", {}),
    }
    return ExplorationSuiteReport(
        suite_id="PM028-E6-SCALE",
        generator_version=static_case.generator_version,
        results=(static_result, simulation_result),
        coverage=coverage,
        checks=checks,
        metadata={
            "source_report": str(path),
            "evidence_tier": payload.get("tier"),
            "git_dirty": static.get("environment", {}).get("git_dirty"),
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
