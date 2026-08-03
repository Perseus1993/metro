from __future__ import annotations

from functools import lru_cache

from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station_testkit.layout_quality import inspect_layout_quality
from metro_station_testkit.topology_trial_catalog import topology_core_cases
from metro_station_testkit.topology_trial_designs import generate_topology_trial_design


@lru_cache(maxsize=1)
def boundary_baseline() -> StationDesignDocument:
    return generate_topology_trial_design(topology_core_cases()[0])


def design_validation_result(
    document: StationDesignDocument,
) -> tuple[bool, tuple[str, ...]]:
    issues = validate_station_design(document)
    codes = tuple(issue.code for issue in issues)
    return not any(issue.severity == "error" for issue in issues), codes


def quality_validation_result(
    document: StationDesignDocument,
) -> tuple[bool, tuple[str, ...]]:
    report = inspect_layout_quality(document)
    codes = tuple(issue.code for issue in report.issues)
    return not any(issue.severity == "error" for issue in report.issues), codes

