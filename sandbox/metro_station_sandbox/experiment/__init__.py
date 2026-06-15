"""Batch simulation experiments for station design alternatives."""

from typing import Any

__all__ = [
    "CaseResult",
    "ExperimentCase",
    "ExperimentRunner",
    "TrajectoryReport",
    "TrajectoryThresholds",
    "diagnose_tracks",
    "write_experiment_report",
]


def __getattr__(name: str) -> Any:
    if name in {"TrajectoryReport", "TrajectoryThresholds", "diagnose_tracks"}:
        from . import diagnosis

        return getattr(diagnosis, name)
    if name == "write_experiment_report":
        from . import report

        return getattr(report, name)
    if name in {"CaseResult", "ExperimentCase", "ExperimentRunner"}:
        from . import runner

        return getattr(runner, name)
    raise AttributeError(name)
