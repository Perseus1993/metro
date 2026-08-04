"""Compatibility command; use ``metro_station_experiments.analysis.vertical`` instead."""

from metro_station_experiments.analysis.vertical import *  # noqa: F403
from metro_station_experiments.analysis.vertical import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
