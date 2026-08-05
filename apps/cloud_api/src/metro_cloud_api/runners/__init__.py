from __future__ import annotations

import os

from metro_cloud_api.runner import SimulationRunner


def get_runner_by_kind(kind: str) -> SimulationRunner:
    if kind == "fake":
        from .fake import FakeRunner

        return FakeRunner(
            seconds_per_tick=float(os.environ.get("METRO_FAKE_SECONDS_PER_TICK", "0"))
        )
    if kind == "real":
        from .metro_station import MetroStationRunner

        return MetroStationRunner()
    raise ValueError(f"unknown runner kind: {kind}")
