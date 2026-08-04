from types import SimpleNamespace

from metro_station.adapters.simulation.facilities.filters import (
    filter_vertical_transfers_for_passenger,
)
from metro_station.adapters.simulation.planning.plan import AgentIntent


def _candidate(
    facility_id: str,
    *,
    kind: str,
    capacity: int | None = None,
):
    candidate = SimpleNamespace(
        facility_id=facility_id,
        spec=SimpleNamespace(
            kind=kind,
            direction="down",
            entry_level_id="b1",
        ),
    )
    if capacity is not None:
        candidate.cabin_capacity_persons = capacity
    return candidate


def test_oversized_group_replans_before_an_elevator_fifo_claim() -> None:
    passenger = SimpleNamespace(
        group_size=3,
        current_level_id="b1",
        intent=AgentIntent.ENTER_AND_BOARD.value,
        evacuation_facility_path=(),
    )
    elevator = _candidate("elevator", kind="elevator", capacity=2)
    stairs = _candidate("stairs", kind="stairs")

    candidates = filter_vertical_transfers_for_passenger(
        passenger,
        (elevator, stairs),
    )

    assert candidates == [stairs]
    assert filter_vertical_transfers_for_passenger(passenger, (elevator,)) == []
