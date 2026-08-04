from __future__ import annotations

import argparse
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from time import monotonic
from zipfile import ZipFile

from metro_station.adapters.simulation.comparison import MesaComparisonExecutor
from metro_station.adapters.simulation.design.schema import DesignElement, ElementGeometry
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.application.analysis_cases import (
    AnalysisCase,
    clone_analysis_case,
    create_analysis_case,
    revise_case,
)
from metro_station.application.comparisons import (
    AnalystDecision,
    ComparisonRunSpec,
    RunSummary,
)
from metro_station.bootstrap import execute_analysis_comparison
from metro_station_designer.comparison_report_export import comparison_report_bundle


DEFAULT_OUTPUT = Path("output/analysis_comparison_acceptance")
SEEDS = (7, 42, 99)


def run_acceptance(output_dir: Path = DEFAULT_OUTPUT) -> dict:
    started = monotonic()
    spec = _water_barrier_spec()
    report = execute_analysis_comparison(spec)
    report = replace(
        report,
        decision=AnalystDecision(
            "more_evidence",
            "Automated acceptance records evidence only; an analyst must make the decision.",
            "acceptance-harness",
        ),
    )
    bundle = comparison_report_bundle(report)
    expected = next(run for run in report.runs if run.role == "baseline" and run.seed == SEEDS[0])
    replay_matches = _verify_bundle_replay(bundle, report.spec, expected)
    manifest = _manifest(report.as_dict(), replay_matches, monotonic() - started)
    _write_outputs(output_dir, report.as_dict(), bundle, manifest)
    _assert_acceptance(report.as_dict(), manifest)
    return manifest


def _water_barrier_spec() -> ComparisonRunSpec:
    baseline_design = create_design("single_level_terminal")
    barrier = DesignElement(
        id="water_barrier_a",
        kind="obstacle",
        level_id="l1_terminal",
        geometry=ElementGeometry(
            shape="rect",
            x_m=50.0,
            y_m=28.0,
            width_m=2.0,
            height_m=1.5,
        ),
        label="Water barrier A",
        role="obstacle",
        metadata={"blocking": True, "visual_kind": "water_barrier"},
    )
    candidate_design = replace(
        baseline_design,
        id=f"{baseline_design.id}_water_barrier_a",
        label=f"{baseline_design.label} + water barrier A",
        elements=(*baseline_design.elements, barrier),
    )
    baseline = create_analysis_case(
        name="Baseline",
        design=baseline_design.as_dict(),
        operations={"entry_count_hour": 120, "exit_count_hour": 60},
        simulation={
            "demand_minutes": 1,
            "horizon_minutes": 4,
            "tick_seconds": 10,
            "movement_backend": "batched_jupedsim",
        },
        seeds=SEEDS,
        metadata={"station_name": "water-barrier-acceptance"},
    )
    candidate = revise_case(
        clone_analysis_case(baseline, name="Candidate water barrier"),
        design=candidate_design.as_dict(),
    )
    return ComparisonRunSpec.create(baseline, candidate)


def _verify_bundle_replay(
    bundle: bytes,
    original: ComparisonRunSpec,
    expected: RunSummary,
) -> bool:
    with ZipFile(BytesIO(bundle)) as archive:
        baseline = _case_from_archive(archive, "baseline.analysis-case.json")
        candidate = _case_from_archive(archive, "candidate.analysis-case.json")
    imported_spec = ComparisonRunSpec(
        experiment_id=original.experiment_id,
        baseline=baseline,
        candidate=candidate,
        seeds=original.seeds,
        density_radius_m=original.density_radius_m,
        density_threshold_persons_m2=original.density_threshold_persons_m2,
    )
    replay = MesaComparisonExecutor().execute(
        baseline,
        seed=SEEDS[0],
        role="baseline",
        spec=imported_spec,
    )
    return replay.as_dict() == expected.as_dict()


def _case_from_archive(archive: ZipFile, name: str) -> AnalysisCase:
    return AnalysisCase.from_dict(json.loads(archive.read(name)))


def _manifest(report: dict, replay_matches: bool, wall_seconds: float) -> dict:
    return {
        "status": "pass" if report["status"] == "completed" and replay_matches else "fail",
        "experiment_id": report["spec"]["experiment_id"],
        "schemas": {
            "case": report["spec"]["baseline"]["schema_version"],
            "spec": report["spec"]["schema_version"],
            "report": report["schema_version"],
        },
        "seeds": report["spec"]["seeds"],
        "run_count": len(report["runs"]),
        "input_differences": report["input_differences"],
        "bundle_replay_matches": replay_matches,
        "wall_seconds": round(wall_seconds, 3),
    }


def _write_outputs(output_dir: Path, report: dict, bundle: bytes, manifest: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "comparison-report.zip").write_bytes(bundle)
    (output_dir / "acceptance-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(_readme(manifest), encoding="utf-8")


def _readme(manifest: dict) -> str:
    differences = ", ".join(item["path"] for item in manifest["input_differences"])
    return (
        "# 水马 A/B 自动验收\n\n"
        f"- 状态：{manifest['status']}\n"
        f"- 固定种子：{manifest['seeds']}\n"
        f"- 配对运行：{manifest['run_count']} 次\n"
        f"- 唯一输入差异：{differences}\n"
        f"- 报告包导入复跑一致：{manifest['bundle_replay_matches']}\n"
        f"- 墙钟时间：{manifest['wall_seconds']} 秒\n\n"
        "自动验收不替代分析人员决策、真实用户任务测试或模型校准。\n"
    )


def _assert_acceptance(report: dict, manifest: dict) -> None:
    assert manifest["status"] == "pass"
    assert manifest["run_count"] == 6
    assert manifest["seeds"] == list(SEEDS)
    assert [item["path"] for item in report["input_differences"]] == [
        "design.elements.water_barrier_a"
    ]
    assert {(run["role"], run["seed"]) for run in report["runs"]} == {
        (role, seed) for seed in SEEDS for role in ("baseline", "candidate")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the V0.1 water-barrier A/B acceptance.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = run_acceptance(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
