from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from metro_station.bootstrap import (
    run_designer,
    run_simulation,
    validate_design_template,
    validate_routing_plugin,
)


def _validate_design(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="metro-station validate-design")
    parser.add_argument("--design-template", default="visual_demo_station")
    args = parser.parse_args(list(arguments))
    payload = validate_design_template(args.design_template)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["valid"] else 1


def _validate_routing_plugin(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="metro-station validate-routing-plugin")
    parser.add_argument("manifest")
    parser.add_argument("--parameters", default="{}", help="JSON object")
    parser.add_argument("--timeout-seconds", type=float, default=2.0)
    args = parser.parse_args(list(arguments))
    parameters = json.loads(args.parameters)
    if not isinstance(parameters, dict):
        raise SystemExit("--parameters must contain a JSON object")
    payload = validate_routing_plugin(
        args.manifest,
        parameters=parameters,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


def _print_help() -> None:
    print(
        "\n".join(
            (
                "usage: metro-station <command> [options]",
                "",
                "commands:",
                "  simulate         run the official Mesa + JuPedSim simulation",
                "  designer         serve the station design inspector",
                "  validate-design  validate a built-in station design",
                "  validate-routing-plugin  run the 10-case routing SDK contract suite",
                "",
                "Run 'metro-station simulate --help' for simulation options.",
            )
        )
    )


def main(arguments: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if arguments is None else arguments)
    if not argv or argv[0] in {"-h", "--help"}:
        _print_help()
        return

    command, *command_arguments = argv
    if command == "simulate":
        run_simulation(command_arguments)
        return
    if command == "designer":
        run_designer(command_arguments)
        return
    if command == "validate-design":
        raise SystemExit(_validate_design(command_arguments))
    if command == "validate-routing-plugin":
        raise SystemExit(_validate_routing_plugin(command_arguments))

    # Compatibility for callers that used the legacy option-only CLI.
    if command.startswith("-"):
        run_simulation(argv)
        return
    raise SystemExit(f"unknown metro-station command: {command}")
