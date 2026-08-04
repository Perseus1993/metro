from __future__ import annotations

from metro_station_acceptance.capacity_convergence_acceptance import (
    inspect_capacity_convergence,
)


def test_capacity_convergence_has_explicit_monotonic_boundary() -> None:
    report = inspect_capacity_convergence()

    assert report["capacity_semantics"] == "constructive_safe_lower_bound"
    assert report["status"] == "ok", report
    assert all(report["checks"].values())
    assert all(
        item["status"] == "ok" for item in report["certificate_boundary_probes"]
    )
    assert all(item["status"] == "ok" for item in report["demand_boundary_probes"])
    assert all(item["status"] == "ok" for item in report["scenario_probes"])
