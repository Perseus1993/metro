"""Compatibility CLI for the former sandbox entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from metro_station.bootstrap import run_designer, run_simulation


def _option(arguments: Sequence[str], name: str, default: str) -> str:
    try:
        index = arguments.index(name)
    except ValueError:
        return default
    return arguments[index + 1] if index + 1 < len(arguments) else default


def _simulation_arguments(arguments: Sequence[str]) -> list[str]:
    result: list[str] = []
    skip_value = False
    for argument in arguments:
        if skip_value:
            skip_value = False
            continue
        if argument in {"--host", "--port"}:
            skip_value = True
            continue
        if argument in {"--serve", "--serve-inspector"}:
            continue
        result.append(argument)
    return result


def main(arguments: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if arguments is None else arguments)
    host = _option(argv, "--host", "127.0.0.1")
    port = _option(argv, "--port", "8765")
    if "--serve-inspector" in argv:
        run_designer(("--host", host, "--port", port))
        return

    run_simulation(_simulation_arguments(argv))
    if "--serve" not in argv:
        return

    from metro_station_visualizer.cli import main as serve_visualizer

    serve_visualizer(("--host", host, "--port", port))


if __name__ == "__main__":
    main()
