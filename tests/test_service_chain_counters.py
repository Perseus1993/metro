from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from metro_station.adapters.simulation.runtime.service_chain_counters import (
    STALLED_PLATFORM_PARKING,
    WAITING_CAPACITY_RETRY,
    increment_service_chain_counter,
)


def test_service_chain_counter_is_independent_of_audit_logging() -> None:
    model = SimpleNamespace(service_chain_event_counts=Counter())

    increment_service_chain_counter(model, WAITING_CAPACITY_RETRY)
    increment_service_chain_counter(model, WAITING_CAPACITY_RETRY)
    increment_service_chain_counter(model, STALLED_PLATFORM_PARKING)

    assert model.service_chain_event_counts == {
        WAITING_CAPACITY_RETRY: 2,
        STALLED_PLATFORM_PARKING: 1,
    }
