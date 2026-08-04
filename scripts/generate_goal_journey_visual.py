from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from metro_station_visualizer.config import ASSET_DIR

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sandbox.metro_station_sandbox.planning.goal_graph_io import (  # noqa: E402
    journey_graph_to_dict,
)
from metro_station_testkit.goal_journey_probe import (  # noqa: E402
    GoalJourneyPhysicalProbe,
)


DEFAULT_OUTPUT = ASSET_DIR / "goal_journey_demo_data.js"


def build_visual_payload(
    *,
    seed: int = 42,
    scenario_id: str = "natural_full_journey",
) -> dict[str, Any]:
    probe = GoalJourneyPhysicalProbe(scenario_id, seed=seed)
    result = probe.run()
    if result.status != "ok":
        raise RuntimeError(f"{scenario_id} is not visualizable: {result.checks}")
    scene = probe.scene
    return {
        "title": "单旅客进站到上车",
        "scenario_id": scenario_id,
        "mode": (
            "single_passenger_crowded_scene"
            if scenario_id == "crowded_full_journey"
            else "single_passenger_clear_scene"
        ),
        "seed": seed,
        "duration_seconds": result.elapsed_seconds,
        "world": {"width": scene.width, "height": scene.height},
        "regions": {
            name: list(position) for name, position in scene.region_positions.items()
        },
        "facilities": [
            {
                "id": item.facility_id,
                "kind": item.spec.kind,
                "stage": item.spec.stage,
                "position": list(item.spec.position),
                "queue_anchor": list(item.spec.queue_anchor),
                "exit_position": list(item.spec.exit_position),
                "entry_level": item.spec.entry_level_id,
                "exit_level": item.spec.exit_level_id,
            }
            for item in scene.facilities
        ],
        "graph": journey_graph_to_dict(probe.graph),
        "frames": probe.physical_frames,
        "traces": [trace.as_dict() for trace in result.traces],
        "service_events": [event.as_dict() for event in scene.facility_service_events],
        "checks": result.checks,
        "background_crowd_size": len(scene.crowd),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate the journey Graph visual data")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scenario",
        choices=("natural_full_journey", "crowded_full_journey"),
        default="natural_full_journey",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_visual_payload(seed=args.seed, scenario_id=args.scenario)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.GOAL_JOURNEY_DEMO_DATASETS = window.GOAL_JOURNEY_DEMO_DATASETS || {};\n"
        + f"window.GOAL_JOURNEY_DEMO_DATASETS[{json.dumps(args.scenario)}] = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(
        f"[GOAL-JOURNEY-VISUAL] frames={len(payload['frames'])} "
        f"traces={len(payload['traces'])} output={args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
