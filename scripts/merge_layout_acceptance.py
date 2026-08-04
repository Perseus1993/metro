from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from metro_station_acceptance.layout_acceptance_merge import (  # noqa: E402
    merge_layout_acceptance_payloads,
    render_merged_layout_acceptance_markdown,
)
from metro_station_acceptance.generated_scale_acceptance import (  # noqa: E402
    GENERATED_SCALE_SHARD_SCHEMA_VERSION,
    merge_generated_scale_shards,
    merge_generated_simulation_shards,
)


DEFAULT_JSON = ROOT / "output" / "layout_acceptance" / "release_report.json"
DEFAULT_MARKDOWN = ROOT / "output" / "layout_acceptance" / "release_report.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge sharded layout acceptance reports")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.inputs]
    if all(
        payload.get("generated_layouts", {}).get("schema_version")
        == GENERATED_SCALE_SHARD_SCHEMA_VERSION
        for payload in payloads
    ):
        generated = merge_generated_scale_shards(
            tuple(payload["generated_layouts"] for payload in payloads)
        )
        simulation_payloads = tuple(
            payload["generated_simulation"]
            for payload in payloads
            if payload.get("generated_simulation") is not None
        )
        generated_simulation = (
            merge_generated_simulation_shards(simulation_payloads)
            if len(simulation_payloads) == len(payloads)
            else None
        )
        merged = {
            "schema_version": "layout_acceptance_run_merged.v2",
            "status": (
                "ok"
                if generated["status"] == "ok"
                and (generated_simulation is None or generated_simulation["status"] == "ok")
                else "review"
            ),
            "tier": payloads[0].get("tier"),
            "generated_layouts": generated,
            "generated_simulation": generated_simulation,
            "source_reports": tuple(str(path) for path in args.inputs),
            "failure_sources": {
                recipe_id: tuple(
                    str(path)
                    for path, payload in zip(args.inputs, payloads)
                    if recipe_id
                    in set(payload["generated_layouts"].get("failed_recipe_ids", ()))
                )
                for recipe_id in generated["failed_recipe_ids"]
            },
        }
        markdown = _render_generated_merge(merged)
    else:
        merged = merge_layout_acceptance_payloads(payloads)
        markdown = render_merged_layout_acceptance_markdown(merged)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_markdown.write_text(markdown, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": merged["status"],
                "layouts": merged.get("layout_ids", ()),
                "generated_cases": len(merged.get("generated_layouts", {}).get("records", ())),
            }
        )
    )
    return 0 if merged["status"] == "ok" else 1


def _render_generated_merge(payload: dict) -> str:
    generated = payload["generated_layouts"]
    simulation = payload.get("generated_simulation")
    lines = [
        "# Generated layout acceptance merge",
        "",
        f"- Status: **{payload['status'].upper()}**",
        f"- Static cases: `{len(generated['records'])}`",
        f"- Static shards: `{generated['shard_count']}`",
        f"- Canonical fingerprint: `{generated['canonical_fingerprint']}`",
        f"- Simulation samples: `{0 if simulation is None else len(simulation['records'])}`",
        "",
        "## Blocking cases",
        "",
    ]
    failures = tuple(generated.get("failed_recipe_ids", ()))
    if simulation is not None:
        failures = (*failures, *simulation.get("failed_recipe_ids", ()))
    lines.extend(f"- `{item}`" for item in failures)
    if not failures:
        lines.append("- None")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
