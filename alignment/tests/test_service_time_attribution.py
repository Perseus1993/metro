from __future__ import annotations

from types import SimpleNamespace

from metro_alignment.service_time_attribution import (
    TRAVEL_BREAKDOWN_PHASES,
    AdmissionTimeAttribution,
)


class _Gate:
    def __init__(self, *, queue=(), active_passes=(), ready=False) -> None:
        self.queue = list(queue)
        self.active_passes = list(active_passes)
        self._ready = ready

    def _passenger_ready_for_service(self, passenger) -> bool:
        return self._ready and bool(self.queue) and self.queue[0] is passenger


def _passenger(
    passenger_id: int,
    *,
    completed: str | None = None,
    state: str = "walking_to_exit_gate",
    velocity: tuple[float, float] = (1.0, 0.0),
):
    return SimpleNamespace(
        unique_id=passenger_id,
        last_completed_facility_id=completed,
        state=state,
        last_walk_velocity_mps=velocity,
    )


def test_attribution_phases_are_mutually_exclusive_and_exhaustive() -> None:
    moving = _passenger(1)
    stationary = _passenger(6, velocity=(0.0, 0.0))
    upstream_wait = _passenger(7, state="queueing_vertical")
    upstream_service = _passenger(8, state="riding_vertical")
    unclassified = SimpleNamespace(
        unique_id=9,
        last_completed_facility_id=None,
        state="walking_to_exit_gate",
    )
    queued = _passenger(2)
    queue_head = _passenger(3)
    blocked = _passenger(4)
    completed = _passenger(5, completed="entry_gate:lane_1")
    earlier_head = _passenger(99)
    blocked_pass = SimpleNamespace(passenger=blocked, blocked_seconds=1.0)
    model = SimpleNamespace(
        step_index=1,
        passengers=[
            moving,
            stationary,
            upstream_wait,
            upstream_service,
            unclassified,
            queued,
            queue_head,
            blocked,
            completed,
        ],
        gates=[
            _Gate(queue=(earlier_head, queued)),
            _Gate(queue=(queue_head,), ready=True),
            _Gate(active_passes=(blocked_pass,)),
        ],
        exit_gates=[],
        alignment_admission_resources={
            "entry": SimpleNamespace(owners=(1, 2, 3, 4, 5, 6, 7, 8, 9)),
        },
    )
    attribution = AdmissionTimeAttribution()

    attribution.observe(model, release_prefix_by_flow={"entry": "entry_gate:"})
    attribution.observe(model, release_prefix_by_flow={"entry": "entry_gate:"})

    metrics = attribution.metrics()["entry"]
    assert metrics["phase_total_steps"] == {
        "travel": 5,
        "queue": 1,
        "service_ready_wait": 1,
        "release_blocked": 1,
        "completion": 1,
    }
    assert metrics["travel_breakdown_total_steps"] == {
        segment: 1 for segment in TRAVEL_BREAKDOWN_PHASES
    }
    assert metrics["state_total_steps"] == {
        "queueing_vertical": 1,
        "riding_vertical": 1,
        "walking_to_exit_gate": 7,
    }


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


def test_missing_owner_is_explicitly_unclassified() -> None:
    model = SimpleNamespace(
        step_index=1,
        passengers=[],
        gates=[],
        exit_gates=[],
        alignment_admission_resources={
            "exit": SimpleNamespace(owners=(42,)),
        },
    )
    attribution = AdmissionTimeAttribution()

    attribution.observe(model, release_prefix_by_flow={"exit": "exit_gate:"})

    metrics = attribution.metrics()["exit"]
    assert metrics["phase_total_steps"]["travel"] == 1
    assert metrics["travel_breakdown_total_steps"]["unclassified"] == 1
    assert metrics["state_total_steps"] == {"missing_passenger": 1}
