from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.design.schema import (  # noqa: E402
    StationDesignDocument,
)
from metro_station_designer.server import (  # noqa: E402
    build_design_payload,
    compile_react_flow_payload,
    template_catalog_payload,
)
from metro_station_acceptance.preset_acceptance import (  # noqa: E402
    run_preset_acceptance_case,
)
from metro_station_acceptance.preset_acceptance_report import (  # noqa: E402
    render_preset_acceptance_markdown,
)


DEFAULT_OUTPUT = ROOT / "output" / "station_preset_acceptance"
SCRATCH_TEMPLATES = ("scratch_single_level", "scratch_two_level", "scratch_three_level")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate every guided station preset end to end")
    parser.add_argument("--seeds", nargs="+", type=int, default=[41, 42, 43])
    parser.add_argument("--minutes", type=int, default=12)
    parser.add_argument("--demand-minutes", type=int, default=1)
    parser.add_argument("--rate-per-hour", type=int, default=600)
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tracks_dir = args.output_dir / "tracks"
    designs_dir = args.output_dir / "designs"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    designs_dir.mkdir(parents=True, exist_ok=True)

    operations = {
        "minutes": args.minutes,
        "group_size": 1,
        "entry_count_hour": args.rate_per_hour,
        "exit_count_hour": args.rate_per_hour,
        "transfer_count_hour": args.rate_per_hour,
    }
    layouts = _frontend_preset_layouts(operations)
    runs: list[dict[str, Any]] = []
    presets: list[dict[str, Any]] = []
    for layout in layouts:
        preset_id = str(layout["preset"]["id"])
        compiled = _compile_layout(layout, operations)
        _write_json(designs_dir / f"{preset_id}.json", compiled)
        preset_result = {
            "preset_id": preset_id,
            "label": layout["preset"]["label"],
            "config": layout["preset"]["config"],
            "template_id": layout["template_id"],
            "auto_layout_counts": layout.get("counts", {}),
            "compile_summary": compiled["summary"],
        }
        presets.append(preset_result)
        document = StationDesignDocument.from_dict(compiled["document"])
        for seed in args.seeds:
            run, tracks = run_preset_acceptance_case(
                preset_id=preset_id,
                document=document,
                operations=compiled["operations"],
                seed=seed,
                minutes=args.minutes,
                demand_minutes=args.demand_minutes,
                sample_count=args.sample_count,
            )
            run["compile_summary"] = compiled["summary"]
            run["checks"]["design_compiles_without_errors"] = (
                compiled["summary"]["validation_errors"] == 0
                and compiled["summary"]["graph_errors"] == 0
            )
            run["status"] = "ok" if all(run["checks"].values()) else "review"
            runs.append(run)
            _write_json(tracks_dir / f"{preset_id}_seed_{seed}.json", tracks, compact=True)
            print(
                f"[{run['status'].upper()}] {preset_id} seed={seed} "
                f"spawned={run['spawned_persons']} cleared={run['clearance_time_s']}s "
                f"samples={len(run['sampled_trajectories'])}"
            )

    report = {
        "schema_version": "station_preset_acceptance.v1",
        "status": "ok" if runs and all(run["status"] == "ok" for run in runs) else "review",
        "seeds": args.seeds,
        "minutes": args.minutes,
        "demand_minutes": args.demand_minutes,
        "rate_per_hour": args.rate_per_hour,
        "totals": {
            "runs": len(runs),
            "spawned_persons": sum(run["spawned_persons"] for run in runs),
            "terminal_persons": sum(run["terminal_persons"] for run in runs),
            "sampled_trajectories": sum(
                len(run["sampled_trajectories"]) for run in runs
            ),
        },
        "presets": presets,
        "runs": runs,
    }
    _write_json(args.output_dir / "acceptance.json", report)
    (args.output_dir / "acceptance.md").write_text(
        render_preset_acceptance_markdown(report),
        encoding="utf-8",
    )
    print(f"report={args.output_dir / 'acceptance.json'} status={report['status']}")
    return 0 if report["status"] == "ok" else 1


def _frontend_preset_layouts(operations: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = template_catalog_payload()
    payload = {
        "base_nodes_by_template": {
            template_id: build_design_payload(template_id)["react_flow"]["nodes"]
            for template_id in SCRATCH_TEMPLATES
        },
        "component_palette": catalog["component_palette"],
        "passenger_flow_palette": catalog["passenger_flow_palette"],
        "operations": operations,
    }
    completed = subprocess.run(
        ["node", str(ROOT / "scripts" / "station_preset_layout_bridge.mjs")],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    layouts = json.loads(completed.stdout)
    errors = [item["error"] for item in layouts if item.get("error")]
    if errors:
        raise RuntimeError("; ".join(errors))
    return layouts


def _compile_layout(layout: dict[str, Any], operations: dict[str, Any]) -> dict[str, Any]:
    compiled = compile_react_flow_payload(
        {
            "template_id": layout["template_id"],
            "nodes": layout["nodes"],
            "edges": [],
            "operations": operations,
            "generate_station": True,
        }
    )
    if compiled["summary"]["status"] == "error":
        raise RuntimeError(f"{layout['preset']['id']} compile failed: {compiled['summary']}")
    return compiled


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    kwargs = {"ensure_ascii": False, "separators": (",", ":")} if compact else {
        "ensure_ascii": False,
        "indent": 2,
    }
    path.write_text(json.dumps(payload, **kwargs), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
