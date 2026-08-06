from __future__ import annotations

import pytest

from metro_station.adapters.simulation.runtime.external_demand_reservoir import (
    DemandReservoirStateError,
    DemandSourceKind,
    DemandTicketState,
    ExternalDemandReservoir,
    InvalidDemandConfiguration,
    TemporaryDemandBlockReason,
)


def test_entry_queue_has_stable_ids_and_no_logical_capacity_limit() -> None:
    reservoir = ExternalDemandReservoir()

    tickets = [
        reservoir.enqueue(
            scheduled_step=index,
            intent="enter_and_board",
            group_size=1,
            source_kind=DemandSourceKind.ENTRY,
            source_ref="entrance:a",
        )
        for index in range(1_000)
    ]

    assert [ticket.sequence_id for ticket in tickets] == list(range(1_000))
    assert reservoir.peek_head(DemandSourceKind.ENTRY, "entrance:a") == tickets[0]


def test_fifo_claim_and_typed_defer_preserve_the_boundary_head() -> None:
    reservoir = ExternalDemandReservoir()
    first = reservoir.enqueue(
        scheduled_step=3,
        intent="enter_and_board",
        group_size=2,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:a",
    )
    reservoir.enqueue(
        scheduled_step=3,
        intent="enter_and_board",
        group_size=2,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:a",
    )

    claim = reservoir.claim_next(DemandSourceKind.ENTRY, "entrance:a", step=3)
    assert claim is not None and claim.ticket == first
    with pytest.raises(DemandReservoirStateError, match="active claim"):
        reservoir.claim_next(DemandSourceKind.ENTRY, "entrance:a", step=3)
    with pytest.raises(TypeError, match="must be typed"):
        reservoir.defer(claim, step=4, reason="source_placement_blocked")  # type: ignore[arg-type]

    reservoir.defer(
        claim,
        step=4,
        reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
    )

    assert reservoir.peek_head(DemandSourceKind.ENTRY, "entrance:a") == first
    assert reservoir.state_of(first) == DemandTicketState.PENDING
    assert reservoir.deferrals[0].reason == TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED


def test_commit_is_single_publish_and_records_boundary_residence() -> None:
    reservoir = ExternalDemandReservoir()
    first = reservoir.enqueue(
        scheduled_step=2,
        intent="enter_and_board",
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:a",
    )
    second = reservoir.enqueue(
        scheduled_step=2,
        intent="enter_and_board",
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:a",
    )
    claim = reservoir.claim_next(DemandSourceKind.ENTRY, "entrance:a", step=2)
    assert claim is not None

    residence = reservoir.commit(claim, passenger_id=41, published_step=7)

    assert residence.ticket == first
    assert residence.residence_steps == 5
    assert residence.outcome == DemandTicketState.PUBLISHED
    assert reservoir.peek_head(DemandSourceKind.ENTRY, "entrance:a") == second
    with pytest.raises(DemandReservoirStateError, match="stale"):
        reservoir.commit(claim, passenger_id=42, published_step=7)

    next_claim = reservoir.claim_next(DemandSourceKind.ENTRY, "entrance:a", step=7)
    assert next_claim is not None
    with pytest.raises(DemandReservoirStateError, match="passenger_id already"):
        reservoir.commit(next_claim, passenger_id=41, published_step=7)


def test_validate_commit_keeps_claim_until_the_external_transaction_commits() -> None:
    reservoir = ExternalDemandReservoir()
    ticket = reservoir.enqueue(
        scheduled_step=2,
        intent="exit_station",
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:7",
        departure_deadline_step=15,
    )
    claim = reservoir.claim_next(
        DemandSourceKind.TRAIN_ALIGHTING,
        "arrival:7",
        step=4,
    )
    assert claim is not None

    reservoir.validate_commit(claim, passenger_id=41, published_step=7)

    assert reservoir.state_of(ticket) == DemandTicketState.CLAIMED
    assert reservoir.peek_head(DemandSourceKind.TRAIN_ALIGHTING, "arrival:7") == ticket
    with pytest.raises(DemandReservoirStateError, match="active claim"):
        reservoir.claim_next(
            DemandSourceKind.TRAIN_ALIGHTING,
            "arrival:7",
            step=7,
        )

    residence = reservoir.commit(claim, passenger_id=41, published_step=7)
    assert residence.outcome == DemandTicketState.PUBLISHED


def test_claim_cannot_commit_defer_or_close_backwards_in_time() -> None:
    reservoir = ExternalDemandReservoir()
    reservoir.enqueue(
        scheduled_step=2,
        intent="enter_and_board",
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
    )
    claim = reservoir.claim_next(DemandSourceKind.ENTRY, step=7)
    assert claim is not None

    with pytest.raises(DemandReservoirStateError, match="before it was acquired"):
        reservoir.commit(claim, passenger_id=41, published_step=6)
    with pytest.raises(DemandReservoirStateError, match="before it was acquired"):
        reservoir.defer(
            claim,
            step=6,
            reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
        )
    with pytest.raises(DemandReservoirStateError, match="cannot close"):
        reservoir.close(6)

    reservoir.defer(
        claim,
        step=7,
        reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"scheduled_step": -1}, "scheduled step"),
        ({"intent": ""}, "intent"),
        ({"group_size": 0}, "group_size"),
        ({"source_kind": "entry"}, "source_kind"),
        ({"departure_deadline_step": 5}, "entry demand"),
    ],
)
def test_invalid_entry_configuration_fails_fast(kwargs: dict, message: str) -> None:
    values = {
        "scheduled_step": 1,
        "intent": "enter_and_board",
        "group_size": 1,
        "source_kind": DemandSourceKind.ENTRY,
        "source_ref": None,
        "departure_deadline_step": None,
    }
    values.update(kwargs)

    with pytest.raises(InvalidDemandConfiguration, match=message):
        ExternalDemandReservoir().enqueue(**values)


def test_train_alighting_requires_one_arrival_ref_and_deadline() -> None:
    reservoir = ExternalDemandReservoir()
    with pytest.raises(InvalidDemandConfiguration, match="requires an arrival ref"):
        reservoir.enqueue(
            scheduled_step=10,
            intent="exit_station",
            group_size=1,
            source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        )
    with pytest.raises(InvalidDemandConfiguration, match="must follow"):
        reservoir.enqueue(
            scheduled_step=10,
            intent="exit_station",
            group_size=1,
            source_kind=DemandSourceKind.TRAIN_ALIGHTING,
            source_ref="arrival:7",
            departure_deadline_step=10,
        )

    reservoir.enqueue(
        scheduled_step=10,
        intent="exit_station",
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:7",
        departure_deadline_step=15,
    )
    with pytest.raises(InvalidDemandConfiguration, match="multiple deadlines"):
        reservoir.enqueue(
            scheduled_step=11,
            intent="exit_station",
            group_size=1,
            source_kind=DemandSourceKind.TRAIN_ALIGHTING,
            source_ref="arrival:7",
            departure_deadline_step=16,
        )


def test_train_deadline_retires_pending_and_claimed_as_not_alighted() -> None:
    reservoir = ExternalDemandReservoir()
    first = reservoir.enqueue(
        scheduled_step=10,
        intent="exit_station",
        group_size=2,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:7",
        departure_deadline_step=15,
    )
    second = reservoir.enqueue(
        scheduled_step=11,
        intent="exit_station",
        group_size=2,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:7",
        departure_deadline_step=15,
    )
    claim = reservoir.claim_next(
        DemandSourceKind.TRAIN_ALIGHTING,
        "arrival:7",
        step=12,
    )
    assert claim is not None

    retired = reservoir.expire_train_arrival("arrival:7", step=15)

    assert [item.ticket for item in retired] == [first, second]
    assert all(item.outcome == DemandTicketState.NOT_ALIGHTED for item in retired)
    assert all(item.release_reason == "train_alighting_capacity_insufficient" for item in retired)
    assert [item.released_step for item in retired] == [15, 15]
    with pytest.raises(DemandReservoirStateError, match="stale"):
        reservoir.defer(
            claim,
            step=15,
            reason=TemporaryDemandBlockReason.ADMISSION_CREDIT_EXHAUSTED,
        )
    with pytest.raises(InvalidDemandConfiguration, match="already departed"):
        reservoir.enqueue(
            scheduled_step=16,
            intent="exit_station",
            group_size=1,
            source_kind=DemandSourceKind.TRAIN_ALIGHTING,
            source_ref="arrival:7",
            departure_deadline_step=20,
        )


def test_claim_at_departure_expires_capacity_without_throwing() -> None:
    reservoir = ExternalDemandReservoir()
    ticket = reservoir.enqueue(
        scheduled_step=10,
        intent="exit_station",
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:7",
        departure_deadline_step=15,
    )

    claim = reservoir.claim_next(
        DemandSourceKind.TRAIN_ALIGHTING,
        "arrival:7",
        step=15,
    )

    assert claim is None
    assert reservoir.state_of(ticket) == DemandTicketState.NOT_ALIGHTED


def test_close_right_censors_each_boundary_without_pooling_wait() -> None:
    reservoir = ExternalDemandReservoir()
    entry_a = reservoir.enqueue(
        scheduled_step=2,
        intent="enter_and_board",
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:a",
    )
    entry_b = reservoir.enqueue(
        scheduled_step=6,
        intent="enter_and_board",
        group_size=1,
        source_kind=DemandSourceKind.ENTRY,
        source_ref="entrance:b",
    )
    train = reservoir.enqueue(
        scheduled_step=8,
        intent="exit_station",
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:9",
        departure_deadline_step=20,
    )

    retired = reservoir.close(12)

    assert [item.residence_steps for item in retired] == [10, 6, 4]
    assert all(item.right_censored for item in retired)
    assert reservoir.residences_for(DemandSourceKind.ENTRY, "entrance:a")[0].ticket == entry_a
    assert reservoir.residences_for(DemandSourceKind.ENTRY, "entrance:b")[0].ticket == entry_b
    assert (
        reservoir.residences_for(DemandSourceKind.TRAIN_ALIGHTING, "arrival:9")[0].ticket == train
    )
    assert reservoir.close(13) == ()
    with pytest.raises(DemandReservoirStateError, match="closed"):
        reservoir.enqueue(
            scheduled_step=13,
            intent="enter_and_board",
            group_size=1,
            source_kind=DemandSourceKind.ENTRY,
        )


def test_close_after_departure_records_not_alighted_at_the_deadline() -> None:
    reservoir = ExternalDemandReservoir()
    ticket = reservoir.enqueue(
        scheduled_step=10,
        intent="exit_station",
        group_size=1,
        source_kind=DemandSourceKind.TRAIN_ALIGHTING,
        source_ref="arrival:11",
        departure_deadline_step=15,
    )

    [residence] = reservoir.close(18)

    assert residence.ticket == ticket
    assert residence.outcome == DemandTicketState.NOT_ALIGHTED
    assert residence.released_step == 15
    assert residence.residence_steps == 5
