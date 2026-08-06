from __future__ import annotations

from math import hypot

from ..facilities.process import FacilityKind


def advance_stalled_gate_ingress_turn(model, passenger, *, reason: str) -> bool:
    """Advance a reached body-clear gate turn without rebuilding its route."""

    goal = passenger.current_goal
    stage = goal.stage or passenger.goal_runtime.state.current_stage
    approach_claims = passenger.facility_approach_facility_ids_by_stage
    if stage not in approach_claims and len(approach_claims) == 1:
        stage = next(iter(approach_claims))
    if stage is None or not passenger.route:
        return False
    facility_id = approach_claims.get(stage)
    if facility_id is None:
        facility_id = goal.facility_id
    facility = model.facilities_by_id.get(facility_id)
    if facility is None or facility.spec.kind != FacilityKind.GATE.value:
        return False
    if passenger.facility_approach_facility_ids_by_stage.get(stage) != facility.facility_id:
        return False
    slot_index = passenger.facility_approach_slots_by_stage.get(stage)
    if slot_index is None:
        return False
    ingress = model._gate_queue_ingress_anchors(
        passenger,
        facility,
        int(slot_index),
    )
    if not ingress:
        return False
    mouth = ingress[-1]
    if (
        hypot(
            passenger.route[0][0] - mouth[0],
            passenger.route[0][1] - mouth[1],
        )
        > 1e-6
        or hypot(
            passenger.target[0] - mouth[0],
            passenger.target[1] - mouth[1],
        )
        <= 1e-6
    ):
        return False
    distance = hypot(
        passenger.pos[0] - passenger.target[0],
        passenger.pos[1] - passenger.target[1],
    )
    recovery_radius = float(model.scenario.jupedsim_target_radius_units)
    if distance > recovery_radius:
        return False

    reached_turn = tuple(passenger.target)
    passenger._finish_current_target(snap_to_target=False)
    model.audit.record(
        "passenger_advanced_stalled_gate_ingress_turn",
        source="goal_runtime",
        step=int(model.step_index),
        context={
            "passenger_id": int(passenger.unique_id),
            "facility_id": facility.facility_id,
            "stage": stage,
            "reason": reason,
            "distance": float(distance),
            "recovery_radius": recovery_radius,
            "reached_turn": [float(reached_turn[0]), float(reached_turn[1])],
            "next_target": [float(passenger.target[0]), float(passenger.target[1])],
        },
    )
    return True


__all__ = ["advance_stalled_gate_ingress_turn"]
