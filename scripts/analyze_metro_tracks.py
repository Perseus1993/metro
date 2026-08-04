"""Compatibility command; use ``metro_station_experiments.analysis.tracks`` instead."""

from metro_station_experiments.analysis.tracks import *  # noqa: F403
from metro_station_experiments.analysis.tracks import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
