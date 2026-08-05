from __future__ import annotations

from typing import TYPE_CHECKING

from .filters import filter_facilities_for_passenger
from ..planning.plan import AgentIntent, FacilityStage

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from .gate_runtime import GateProcessAgent
    from .runtime_base import FacilityProcessAgent


def direct_boarding_candidates(
    gate: GateProcessAgent,
    passenger: PassengerAgent,
) -> tuple[FacilityProcessAgent, ...]:
    """Return same-level boarding doors requiring admission past this gate."""

    if (
        gate.spec.stage != FacilityStage.ENTRY_GATE.value
        or passenger.intent != AgentIntent.ENTER_AND_BOARD.value
        or gate.model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER.value)
    ):
        return ()
    candidates = filter_facilities_for_passenger(
        passenger,
        FacilityStage.BOARDING_DOOR.value,
        gate.model._facilities_for_stage(FacilityStage.BOARDING_DOOR.value),
    )
    return tuple(
        sorted(
            (
                facility
                for facility in candidates
                if gate.model.facility_portal_binding(
                    facility.facility_id
                ).entry_level_id
                == gate.portal_exit_level_id
            ),
            key=lambda facility: facility.facility_id,
        )
    )


def has_direct_boarding_admission(
    gate: GateProcessAgent,
    passenger: PassengerAgent,
) -> bool:
    if not gate._direct_boarding_candidates(passenger):
        return True
    if int(passenger.unique_id) in gate.model._platform_waiting_reservations:
        return True
    return bool(
        gate.model._available_platform_waiting_slot_count(
            level_id=gate.portal_exit_level_id,
            passenger=passenger,
            limit=1,
        )
    )


def reserve_direct_boarding_admission(
    gate: GateProcessAgent,
    passenger: PassengerAgent,
) -> str | None:
    if not gate._direct_boarding_candidates(passenger):
        return None
    if int(passenger.unique_id) in gate.model._platform_waiting_reservations:
        return None
    platform = gate.model.platform_for_passenger(passenger)
    if platform is None:
        raise RuntimeError("downstream boarding platform unavailable")
    try:
        gate.model._reserve_platform_waiting_slot(passenger, platform)
    except RuntimeError as error:
        raise RuntimeError("downstream boarding capacity unavailable") from error
    return "platform"


__all__ = [
    "direct_boarding_candidates",
    "has_direct_boarding_admission",
    "reserve_direct_boarding_admission",
]
