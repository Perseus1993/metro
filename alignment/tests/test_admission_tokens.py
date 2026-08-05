from __future__ import annotations

import pytest
from metro_station.adapters.simulation.facilities.admission_resource import (
    AdmissionTokenResource,
)

from metro_alignment.admission_tokens import (
    AdmissionTokenPolicy,
    admission_preflight_report,
    required_admission_tokens,
)


def test_required_capacity_uses_littles_law_with_burst_headroom() -> None:
    assert required_admission_tokens(
        count_hour=2500,
        residence_seconds=25.0,
        burst_sigma=3.0,
    ) == 30


def test_missing_residence_evidence_fails_closed() -> None:
    report = AdmissionTokenPolicy("entry", 2500, None, None, None, 3.0).preflight()

    assert report["status"] == "fail"
    assert report["required_capacity"] is None
    assert report["blockers"][0]["code"] == "admission_residence_evidence_missing"


def test_explicit_capacity_is_rejected_when_below_registered_requirement() -> None:
    report = AdmissionTokenPolicy(
        "entry",
        2500,
        25.0,
        "p90",
        "T1_residence_time.json#entry.p90",
        3.0,
        29,
        deterministic_arrival_envelope=30,
    ).preflight()

    assert report["status"] == "fail"
    assert report["required_capacity"] == 30
    assert report["configured_capacity"] == 29


def test_preflight_bundle_requires_both_source_flows() -> None:
    report = admission_preflight_report(
        (
            AdmissionTokenPolicy("entry", 2500, 25.0, "p90", "T1#entry", 3.0),
            AdmissionTokenPolicy("exit", 2200, None, None, None, 3.0),
        )
    )

    assert report["status"] == "fail"
    assert report["blockers"][0]["flow_id"] == "exit"


def test_deterministic_arrival_envelope_is_the_fixed_schedule_requirement() -> None:
    report = AdmissionTokenPolicy(
        "exit",
        2200,
        45.0,
        "p99",
        "T1#exit.p99",
        3.0,
        deterministic_arrival_envelope=73,
    ).preflight()

    assert report["required_capacity"] == 73
    assert report["configured_capacity"] == 73


def test_token_resource_has_no_geometry_and_detects_double_release() -> None:
    resource = AdmissionTokenResource("entry", capacity=1)

    assert resource.acquire("demand:7", 3)
    assert resource.active_residence_steps(5) == [2]
    resource.transfer("demand:7", 7)
    residence = resource.release(7, 11, reason="downstream_stage_released")

    assert residence.residence_steps == 8
    assert resource.available == 1
    assert not any(
        name in resource.__dict__
        for name in ("polygon", "point", "slots", "coordinates")
    )
    with pytest.raises(RuntimeError, match="double-release"):
        resource.release(7, 12, reason="duplicate")


def test_token_resource_close_releases_active_owners_as_right_censored() -> None:
    resource = AdmissionTokenResource("exit", capacity=2)
    assert resource.acquire("p:1", 4)
    assert resource.acquire("p:2", 7)

    residences = resource.close(12)

    assert resource.occupancy == 0
    assert [item.residence_steps for item in residences] == [8, 5]
    assert all(item.right_censored for item in residences)
