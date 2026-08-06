from __future__ import annotations

import pytest

from metro_station.adapters.simulation.runtime.train_exchange_manifest import (
    FAIL_CAPACITY,
    MANIFEST_DEPARTED,
    MANIFEST_FAILED,
    TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT,
    TrainExchangeLifecycleError,
    TrainExchangeManifest,
    TrainRunId,
)


def _manifest(
    *,
    capacity: int = 100,
    inbound: int = 80,
    planned_alight: int = 30,
    through: int = 50,
) -> TrainExchangeManifest:
    return TrainExchangeManifest(
        train_run_id=TrainRunId("platform:L1:up", 3),
        arrival_step=10,
        scheduled_close_step=20,
        capacity_persons=capacity,
        inbound_load_persons=inbound,
        planned_alight_persons=planned_alight,
        through_load_persons=through,
    )


def test_manifest_validates_train_run_and_physical_load_relationships() -> None:
    with pytest.raises(ValueError, match="platform_id"):
        TrainRunId(" ", 1)
    with pytest.raises(ValueError, match="arrival_sequence"):
        TrainRunId("platform:L1:up", 0)
    with pytest.raises(ValueError, match="planned_alight_persons"):
        _manifest(inbound=20, planned_alight=21, through=0)
    with pytest.raises(ValueError, match="inbound_load_persons"):
        _manifest(capacity=50, inbound=51, planned_alight=1, through=50)
    with pytest.raises(ValueError, match="through_load_persons"):
        _manifest(inbound=80, planned_alight=30, through=49)


def test_release_persons_and_groups_cannot_exceed_manifest() -> None:
    manifest = _manifest(planned_alight=10, through=70)

    manifest.release_alighting(4, at_step=11)
    manifest.release_alighting_group(6, at_step=12)

    assert manifest.released_alight_persons == 10
    assert manifest.not_alighted_persons == 0
    assert manifest.release_complete_step == 12
    with pytest.raises(ValueError, match="must not exceed"):
        manifest.release_alighting_group(1, at_step=13)


def test_successful_close_requires_complete_release_before_departure() -> None:
    manifest = _manifest()
    manifest.release_alighting_group(10, at_step=12)
    manifest.release_alighting_group(20, at_step=19)
    manifest.record_boarding(40)

    result = manifest.close(actual_departure_step=20)

    assert result.departed is True
    assert result.status == MANIFEST_DEPARTED
    assert result.failure_code is None
    assert result.not_alighted_persons == 0
    assert result.release_complete_step == 19
    assert result.release_complete_step <= result.actual_departure_step
    assert result.departure_load_persons == 90
    assert result.departure_load_persons <= result.capacity_persons
    assert result.departure_policy == FAIL_CAPACITY


def test_pending_alighting_returns_structured_failure_without_departure() -> None:
    manifest = _manifest()
    manifest.release_alighting(12, at_step=15)

    result = manifest.close(actual_departure_step=20)

    assert result.departed is False
    assert result.status == MANIFEST_FAILED
    assert result.failure_code == TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT
    assert result.planned_alight_persons == 30
    assert result.released_alight_persons == 12
    assert result.not_alighted_persons == 18
    assert result.actual_departure_step is None
    assert manifest.actual_departure_step is None
    assert result.as_dict()["train_run_id"] == {
        "platform_id": "platform:L1:up",
        "arrival_sequence": 3,
    }


@pytest.mark.parametrize("first_operation", ["close", "depart"])
def test_manifest_cannot_be_closed_or_departed_twice(first_operation: str) -> None:
    manifest = _manifest(planned_alight=0, through=80)
    getattr(manifest, first_operation)(actual_departure_step=20)

    with pytest.raises(TrainExchangeLifecycleError, match="already departed"):
        manifest.close(actual_departure_step=21)
    with pytest.raises(TrainExchangeLifecycleError, match="already departed"):
        manifest.depart(actual_departure_step=21)


def test_failed_manifest_is_terminal_and_cannot_release_or_depart() -> None:
    manifest = _manifest()
    manifest.close(actual_departure_step=20)

    with pytest.raises(TrainExchangeLifecycleError, match="already failed"):
        manifest.release_alighting(30, at_step=20)
    with pytest.raises(TrainExchangeLifecycleError, match="already failed"):
        manifest.depart(actual_departure_step=21)


def test_boarding_cannot_make_departure_load_exceed_capacity() -> None:
    manifest = _manifest(capacity=100, inbound=80, planned_alight=10, through=70)
    manifest.release_alighting(10, at_step=11)
    manifest.record_boarding(30)

    with pytest.raises(ValueError, match="onboard load"):
        manifest.record_boarding(1)


def test_boarding_cannot_use_capacity_before_alighters_are_released() -> None:
    manifest = _manifest(capacity=100, inbound=100, planned_alight=30, through=70)

    with pytest.raises(ValueError, match="onboard load"):
        manifest.record_boarding(1)

    manifest.release_alighting(10, at_step=11)
    manifest.record_boarding(10)
    assert manifest.departure_load_persons == 80


def test_exchange_events_respect_arrival_close_timeline() -> None:
    manifest = _manifest()

    with pytest.raises(ValueError, match="arrival_step"):
        manifest.release_alighting(1, at_step=9)
    with pytest.raises(ValueError, match="scheduled_close_step"):
        manifest.release_alighting(1, at_step=21)
    with pytest.raises(ValueError, match="scheduled_close_step"):
        manifest.close(actual_departure_step=19)
