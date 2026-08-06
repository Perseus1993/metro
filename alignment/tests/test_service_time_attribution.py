from __future__ import annotations

from types import SimpleNamespace

from metro_alignment.service_time_attribution import (
    ATTRIBUTION_PHASES,
    AdmissionTimeAttribution,
)


class _Gate:
    def __init__(self, *, queue=(), active_passes=(), ready=False) -> None:
        self.queue = list(queue)
        self.active_passes = list(active_passes)
        self._ready = ready

    def _passenger_ready_for_service(self, passenger) -> bool:
        return self._ready and bool(self.queue) and self.queue[0] is passenger


def _passenger(passenger_id: int, *, completed: str | None = None):
    return SimpleNamespace(
        unique_id=passenger_id,
        last_completed_facility_id=completed,
    )


def test_attribution_phases_are_mutually_exclusive_and_exhaustive() -> None:
    travel = _passenger(1)
    queued = _passenger(2)
    queue_head = _passenger(3)
    blocked = _passenger(4)
    completed = _passenger(5, completed="entry_gate:lane_1")
    earlier_head = _passenger(99)
    blocked_pass = SimpleNamespace(passenger=blocked, blocked_seconds=1.0)
    model = SimpleNamespace(
        step_index=1,
        passengers=[travel, queued, queue_head, blocked, completed],
        gates=[
            _Gate(queue=(earlier_head, queued)),
            _Gate(queue=(queue_head,), ready=True),
            _Gate(active_passes=(blocked_pass,)),
        ],
        exit_gates=[],
        alignment_admission_resources={
            "entry": SimpleNamespace(owners=(1, 2, 3, 4, 5)),
        },
    )
    attribution = AdmissionTimeAttribution()

    attribution.observe(model, release_prefix_by_flow={"entry": "entry_gate:"})
    attribution.observe(model, release_prefix_by_flow={"entry": "entry_gate:"})

    metrics = attribution.metrics()["entry"]
    assert metrics["phase_total_steps"] == {phase: 1 for phase in ATTRIBUTION_PHASES}


def test_release_blocked_counts_only_new_blocked_time() -> None:
    passenger = _passenger(4)
    active = SimpleNamespace(passenger=passenger, blocked_seconds=1.0)
    model = SimpleNamespace(
        step_index=1,
        passengers=[passenger],
        gates=[_Gate(active_passes=(active,))],
        exit_gates=[],
        alignment_admission_resources={
            "exit": SimpleNamespace(owners=(4,)),
        },
    )
    attribution = AdmissionTimeAttribution()

    attribution.observe(model, release_prefix_by_flow={"exit": "exit_gate:"})
    model.step_index = 2
    attribution.observe(model, release_prefix_by_flow={"exit": "exit_gate:"})

    totals = attribution.metrics()["exit"]["phase_total_steps"]
    assert totals["release_blocked"] == 1
    assert totals["completion"] == 1
