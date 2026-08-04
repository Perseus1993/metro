from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from sandbox.metro_station_sandbox.planning.journey_catalog import (
    JourneyGraphCatalog,
)
from sandbox.metro_station_sandbox.planning.journey_catalog_compiler import (
    compile_journey_graph_catalog,
)
from sandbox.metro_station_sandbox.design import create_design
from sandbox.metro_station_sandbox.station.graph import StationGraph


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "sandbox"
    / "metro_station_sandbox"
    / "config"
    / "goal_graph_catalog.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the default JourneyGraph catalog")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--design-template", default="visual_demo_station")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    catalog: JourneyGraphCatalog = compile_journey_graph_catalog(
        StationGraph.from_design(create_design(args.design_template))
    )
    args.output.write_text(
        json.dumps(
            catalog.as_dict(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[GOAL-GRAPH-CATALOG] output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
