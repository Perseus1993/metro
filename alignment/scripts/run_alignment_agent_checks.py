from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_code_review import run as run_paper_methodology
from agent_generality import run as run_generality
from agent_metro_compatibility import run as run_metro_compatibility

from metro_alignment.artifact_io import write_json_atomic

AGENT_RUNNERS: dict[str, Any] = {
    "paper_methodology": run_paper_methodology,
    "industry_review": run_paper_methodology,
    "metro_integration": run_metro_compatibility,
    "metro_compatibility": run_metro_compatibility,
    "generality": run_generality,
    "universal_design": run_generality,
}


def run_all(round_id: int) -> dict[str, Any]:
    agents = {
        "paper_methodology": run_paper_methodology(round_id),
        "metro_integration": run_metro_compatibility(round_id),
        "generality": run_generality(round_id),
    }
    return {
        "round": round_id,
        "status": "pass" if all(item["status"] == "pass" for item in agents.values()) else "fail",
        "agents": agents,
    }


def run_single(round_id: int, agent: str) -> dict[str, Any]:
    if agent not in AGENT_RUNNERS:
        raise ValueError(f"unknown agent: {agent}")
    runner = AGENT_RUNNERS[agent]
    result = runner(round_id)
    return {
        "round": round_id,
        "agent": agent,
        "status": result["status"],
        "result": result,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight multi-angle alignment checks.")
    parser.add_argument("--round", type=int, default=1, dest="round_id")
    parser.add_argument(
        "--agent",
        default="all",
        choices=[
            "all",
            "paper_methodology",
            "industry_review",
            "metro_integration",
            "metro_compatibility",
            "generality",
            "universal_design",
        ],
        help="Run only one agent or all three",
    )
    parser.add_argument("--out", type=Path, default=None, help="Optional output JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.agent == "all":
        payload = run_all(args.round_id)
    else:
        payload = run_single(args.round_id, args.agent)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        write_json_atomic(args.out, payload)
    print(text)
    raise SystemExit(0 if payload["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
