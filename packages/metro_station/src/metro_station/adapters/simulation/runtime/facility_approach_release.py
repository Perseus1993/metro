from __future__ import annotations

from math import hypot

from ..movement.dynamic_body_clearance import minimum_body_clearance


def clear_vacated_facility_targeting_reservations(
    model,
    passenger,
    *,
    schedule_stage=None,
) -> None:
    passenger_id = int(passenger.unique_id)
    if schedule_stage is not None:
        stage = str(getattr(schedule_stage, "value", schedule_stage))
        model._facility_approach_release_pending.add((passenger_id, stage))
    clearance = minimum_body_clearance(model)
    for (owner_id, stage), ownership in tuple(
        model._facility_approach_reservation_registry.items()
    ):
        if (
            int(owner_id) != passenger_id
            or (passenger_id, stage) not in model._facility_approach_release_pending
        ):
            continue
        facility = model._facility_approach_ownership_facility(stage, ownership)
        if facility is None:
            model._clear_facility_targeting_reservation(passenger, stage)
            continue
        target = model._facility_approach_slot_position(facility, int(ownership.slot_index))
        if hypot(passenger.pos[0] - target[0], passenger.pos[1] - target[1]) >= (
            clearance - 1e-9
        ):
            model._clear_facility_targeting_reservation(passenger, stage)
