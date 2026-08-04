from types import SimpleNamespace

from metro_station.adapters.simulation.runtime.passenger_goal_train_observer import (
    PassengerGoalTrainObserver,
)


def _train(*, sequence: int = 3, capacity_remaining: int = 0):
    return SimpleNamespace(
        is_boarding=True,
        line_id="L1",
        direction="up",
        platform_id="platform:L1:up",
        arrival_sequence=sequence,
        capacity_remaining=capacity_remaining,
    )


def test_train_full_fact_is_idempotent_within_one_train_run() -> None:
    train = _train()
    model = SimpleNamespace(current_time_seconds=10.0, trains=[train])
    passenger = SimpleNamespace(
        unique_id=7,
        group_size=1,
        target_line_id="L1",
        assigned_line_id=None,
        target_direction="up",
        assigned_direction=None,
    )
    observer = PassengerGoalTrainObserver()

    first = observer.waiting_event(model, passenger)
    model.current_time_seconds = 15.0
    repeated_poll = observer.waiting_event(model, passenger)
    train.arrival_sequence += 1
    next_train = observer.waiting_event(model, passenger)

    assert first is not None and repeated_poll is not None and next_train is not None
    assert first.event_id == repeated_poll.event_id
    assert next_train.event_id != first.event_id
    assert repeated_poll.time_seconds == 15.0
    assert first.train_platform_id == "platform:L1:up"
    assert first.train_arrival_sequence == 3
    assert next_train.train_arrival_sequence == 4


def test_queued_train_capacity_fact_uses_the_train_run_episode() -> None:
    train = _train()
    facility = object()
    model = SimpleNamespace(
        current_time_seconds=20.0,
        facilities_by_id={"door:1": facility},
        train_for_facility=lambda candidate: train if candidate is facility else None,
    )
    passenger = SimpleNamespace(
        unique_id=8,
        group_size=1,
        goal_runtime=SimpleNamespace(
            state=SimpleNamespace(queued_facility_id="door:1")
        ),
    )
    observer = PassengerGoalTrainObserver()

    first = observer.queued_event(model, passenger)
    model.current_time_seconds = 25.0
    repeated_poll = observer.queued_event(model, passenger)

    assert first is not None and repeated_poll is not None
    assert first.event_id == repeated_poll.event_id
    assert first.train_platform_id == "platform:L1:up"
    assert first.train_arrival_sequence == 3
