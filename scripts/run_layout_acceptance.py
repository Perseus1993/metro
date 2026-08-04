from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.layout_acceptance import (  # noqa: E402
    run_cross_layout_acceptance,
)
from metro_station_acceptance.layout_acceptance_contract import (  # noqa: E402
    LAYOUT_IDS,
)
from metro_station_acceptance.layout_acceptance_report import (  # noqa: E402
    render_layout_acceptance_markdown,
)
from metro_station_acceptance.generated_acceptance_profile import (  # noqa: E402
    generated_acceptance_tier_profile,
    trajectory_geometry_corpus,
)
from metro_station_acceptance.generated_layout_evidence import (  # noqa: E402
    render_generated_simulation_markdown,
)
from metro_station_acceptance.generated_geometry_acceptance import (  # noqa: E402
    run_generated_geometry_acceptance,
)
from metro_station_acceptance.generated_scale_acceptance import (  # noqa: E402
    run_generated_scale_shard,
)
from metro_station_acceptance.generated_scale_evidence import (  # noqa: E402
    load_generated_scale_resume,
    render_generated_scale_markdown,
    write_generated_scale_evidence,
    write_generated_scale_record_checkpoint,
)
from metro_station_acceptance.generated_simulation_acceptance import (  # noqa: E402
    run_generated_simulation_acceptance,
)
from metro_station_testkit.layout_corpus import (  # noqa: E402
    generate_geometry_scenario_matrix,
    generate_scenario_corpus,
)


DEFAULT_JSON = ROOT / "output" / "layout_acceptance" / "report.json"
DEFAULT_MARKDOWN = ROOT / "output" / "layout_acceptance" / "report.md"
DEFAULT_GENERATED_EVIDENCE = ROOT / "output" / "layout_acceptance" / "generated"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the shared maturity gate for every station layout"
    )
    parser.add_argument(
        "--tier",
        choices=("geometry", "trajectory", "smoke", "nightly", "release"),
        default="smoke",
    )
    parser.add_argument("--layouts", nargs="+", choices=LAYOUT_IDS, default=list(LAYOUT_IDS))
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument(
        "--generated-profile",
        action="store_true",
        help="run the generated corpus size and simulation sample declared by the tier",
    )
    parser.add_argument("--generated-count", type=int)
    parser.add_argument("--generated-seed", type=int, default=20260716)
    parser.add_argument("--generated-simulation-samples", type=int)
    parser.add_argument("--skip-generated-operations", action="store_true")
    parser.add_argument(
        "--generated-only",
        action="store_true",
        help="skip the fixed-layout maturity matrix and run only the generated corpus",
    )
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="resume a generated shard from a report file or checkpoint directory",
    )
    parser.add_argument(
        "--max-generated-cases",
        type=int,
        help="stop after N new static cases; intended for controlled interruption tests",
    )
    parser.add_argument(
        "--generated-evidence-dir",
        type=Path,
        default=DEFAULT_GENERATED_EVIDENCE,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tier == "geometry":
        _validate_geometry_args(parser, args)
        return _run_geometry_tier(args)
    if args.tier == "trajectory":
        _validate_trajectory_args(parser, args)
        return _run_trajectory_tier(args)
    generated_count, simulation_samples = _generated_counts(args)
    if generated_count < 0 or simulation_samples < 0:
        parser.error("generated counts cannot be negative")
    if simulation_samples > generated_count:
        parser.error("generated simulation samples cannot exceed generated count")
    if args.shard_count <= 0 or args.shard_index < 0 or args.shard_index >= args.shard_count:
        parser.error("shard must satisfy 0 <= shard-index < shard-count")
    if args.generated_only and not generated_count:
        parser.error("--generated-only requires a generated corpus")
    if (args.shard_count != 1 or args.resume_from) and not generated_count:
        parser.error("shard and resume options require a generated corpus")
    report = None
    if not args.generated_only:
        report = run_cross_layout_acceptance(
            tier=args.tier,
            layout_ids=tuple(args.layouts),
            seeds=None if args.seeds is None else tuple(args.seeds),
        )
    generated = None
    generated_simulation = None
    if generated_count:
        corpus = generate_scenario_corpus(
            count=generated_count,
            seed=args.generated_seed,
        )
        evidence_dir = _generated_shard_evidence_dir(args)
        resume_payload = (
            None if args.resume_from is None else load_generated_scale_resume(args.resume_from)
        )
        generated = run_generated_scale_shard(
            corpus,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            resume_payload=resume_payload,
            max_new_cases=args.max_generated_cases,
            workspace=ROOT,
            on_record=lambda record, progress: write_generated_scale_record_checkpoint(
                evidence_dir,
                record,
                progress,
            ),
        )
        write_generated_scale_evidence(generated, evidence_dir)
        if simulation_samples and generated["status"] == "ok":
            generated_simulation = run_generated_simulation_acceptance(
                corpus,
                tier=args.tier,
                sample_size=simulation_samples,
                seeds=None if args.seeds is None else tuple(args.seeds),
                include_operations=not args.skip_generated_operations,
                shard_index=args.shard_index,
                shard_count=args.shard_count,
            )
    overall_ok = report is None or report.status == "ok"
    if generated is not None:
        overall_ok = overall_ok and generated["status"] == "ok"
    if generated_simulation is not None:
        overall_ok = overall_ok and generated_simulation.status == "ok"
    payload = (
        report.as_dict()
        if report is not None
        else {
            "schema_version": "layout_acceptance_run.v2",
            "tier": args.tier,
            "seeds": tuple(args.seeds or generated_acceptance_tier_profile(args.tier).seeds),
            "layouts": (),
            "checks": {"generated_only": True},
        }
    )
    payload["overall_status"] = "ok" if overall_ok else "review"
    payload["generated_layouts"] = generated
    payload["generated_simulation"] = (
        None if generated_simulation is None else generated_simulation.as_dict()
    )
    output_json = _sharded_output_path(args.output_json, args)
    output_markdown = _sharded_output_path(args.output_markdown, args)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown = "" if report is None else render_layout_acceptance_markdown(report)
    if generated is not None:
        markdown += "\n" + render_generated_scale_markdown(generated)
    if generated_simulation is not None:
        markdown += "\n" + render_generated_simulation_markdown(generated_simulation)
    output_markdown.write_text(markdown, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok" if overall_ok else "review",
                "tier": args.tier,
                "layouts": (
                    {} if report is None else {item.layout_id: item.status for item in report.layouts}
                ),
                "output_json": str(output_json),
                "output_markdown": str(output_markdown),
                "generated_layouts": generated_count,
                "generated_simulation_samples": simulation_samples,
                "shard_index": args.shard_index,
                "shard_count": args.shard_count,
            },
            ensure_ascii=False,
        )
    )
    return 0 if overall_ok else 1


def _generated_counts(args: argparse.Namespace) -> tuple[int, int]:
    profile = generated_acceptance_tier_profile(args.tier)
    count = args.generated_count
    samples = args.generated_simulation_samples
    if args.generated_profile:
        count = profile.corpus_size if count is None else count
        samples = profile.simulation_sample_size if samples is None else samples
    return (0 if count is None else count, 0 if samples is None else samples)


def _validate_geometry_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Reject scale/simulation controls that the compiler-only tier cannot honor."""

    unsupported: list[str] = []
    if tuple(args.layouts) != tuple(LAYOUT_IDS):
        unsupported.append("--layouts")
    if args.seeds is not None:
        unsupported.append("--seeds")
    if args.generated_profile:
        unsupported.append("--generated-profile")
    if args.generated_count is not None:
        unsupported.append("--generated-count")
    if args.generated_seed != 20260716:
        unsupported.append("--generated-seed")
    if args.generated_simulation_samples is not None:
        unsupported.append("--generated-simulation-samples")
    if args.skip_generated_operations:
        unsupported.append("--skip-generated-operations")
    if args.generated_only:
        unsupported.append("--generated-only")
    if args.shard_index != 0:
        unsupported.append("--shard-index")
    if args.shard_count != 1:
        unsupported.append("--shard-count")
    if args.resume_from is not None:
        unsupported.append("--resume-from")
    if args.max_generated_cases is not None:
        unsupported.append("--max-generated-cases")
    if args.generated_evidence_dir != DEFAULT_GENERATED_EVIDENCE:
        unsupported.append("--generated-evidence-dir")
    if unsupported:
        parser.error(
            "--tier geometry does not support: " + ", ".join(unsupported)
        )


def _run_geometry_tier(args: argparse.Namespace) -> int:
    payload = run_generated_geometry_acceptance()
    output_json = _sharded_output_path(args.output_json, args)
    output_markdown = _sharded_output_path(args.output_markdown, args)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checks = payload["checks"]
    output_markdown.write_text(
        "# Geometry acceptance\n\n"
        f"- Status: `{payload['status']}`\n"
        f"- Recipes: `{payload['recipe_count']}`\n"
        f"- Wall seconds: `{payload['metrics']['wall_seconds']}`\n"
        + "".join(f"- {name}: `{value}`\n" for name, value in checks.items()),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "tier": "geometry",
                "recipes": payload["recipe_count"],
                "failed_recipes": len(payload["failed_recipes"]),
                "wall_seconds": payload["metrics"]["wall_seconds"],
                "output_json": str(output_json),
                "output_markdown": str(output_markdown),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["status"] == "ok" else 1


def _run_trajectory_tier(args: argparse.Namespace) -> int:
    profile = generated_acceptance_tier_profile("trajectory")
    corpus = trajectory_geometry_corpus(generate_geometry_scenario_matrix())
    if len(corpus.recipes) != profile.corpus_size:
        raise RuntimeError(
            "trajectory profile must sample the frozen 240-recipe geometry matrix"
        )
    report = run_generated_simulation_acceptance(
        corpus,
        tier="trajectory",
        sample_size=profile.simulation_sample_size,
        seeds=profile.seeds,
        include_operations=True,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        shard_by_seed=True,
    )
    payload = report.as_dict()
    payload["profile"] = {
        "recipe_count": profile.simulation_sample_size,
        "seeds": profile.seeds,
        "expected_normal_runs": profile.simulation_sample_size * len(profile.seeds),
        "expected_operational_runs": profile.simulation_sample_size * len(profile.seeds),
    }
    output_json = _sharded_output_path(args.output_json, args)
    output_markdown = _sharded_output_path(args.output_markdown, args)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output_markdown.write_text(
        render_generated_simulation_markdown(report),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report.status,
                "tier": "trajectory",
                "recipes": len(report.global_sampled_recipe_ids),
                "seeds": report.seeds,
                "output_json": str(output_json),
                "output_markdown": str(output_markdown),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report.status == "ok" else 1


def _validate_trajectory_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """Keep the scientific trajectory profile fixed at 16 recipes by 3 seeds."""

    unsupported: list[str] = []
    if tuple(args.layouts) != tuple(LAYOUT_IDS):
        unsupported.append("--layouts")
    if args.seeds is not None:
        unsupported.append("--seeds")
    if args.generated_profile:
        unsupported.append("--generated-profile")
    if args.generated_count is not None:
        unsupported.append("--generated-count")
    if args.generated_simulation_samples is not None:
        unsupported.append("--generated-simulation-samples")
    if args.skip_generated_operations:
        unsupported.append("--skip-generated-operations")
    if args.generated_only:
        unsupported.append("--generated-only")
    if args.resume_from is not None:
        unsupported.append("--resume-from")
    if args.max_generated_cases is not None:
        unsupported.append("--max-generated-cases")
    if args.generated_evidence_dir != DEFAULT_GENERATED_EVIDENCE:
        unsupported.append("--generated-evidence-dir")
    if unsupported:
        parser.error(
            "--tier trajectory has a fixed 16-recipe/3-seed profile and does not "
            "support: " + ", ".join(unsupported)
        )


def _generated_shard_evidence_dir(args: argparse.Namespace) -> Path:
    if args.shard_count == 1:
        return args.generated_evidence_dir
    return args.generated_evidence_dir / (
        f"shard-{args.shard_index:03d}-of-{args.shard_count:03d}"
    )


def _sharded_output_path(path: Path, args: argparse.Namespace) -> Path:
    if args.shard_count == 1:
        return path
    return path.with_name(
        f"{path.stem}.shard-{args.shard_index:03d}-of-{args.shard_count:03d}{path.suffix}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
