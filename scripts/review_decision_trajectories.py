"""Compatibility command; use ``metro_station_experiments.analysis.decisions`` instead."""

from metro_station_experiments.analysis.decisions import *  # noqa: F403
from metro_station_experiments.analysis.decisions import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
