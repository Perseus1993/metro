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
    if stage is None:
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
    distance_to_mouth = hypot(
        passenger.pos[0] - mouth[0],
        passenger.pos[1] - mouth[1],
    )
    if not passenger.route:
        if hypot(
            passenger.target[0] - mouth[0],
            passenger.target[1] - mouth[1],
        ) > 1e-6:
            return False
        bank_mouths: list[tuple[float, float]] = []
        for candidate in model.facilities:
            if (
                candidate.spec.kind != FacilityKind.GATE.value
                or candidate.spec.stage != facility.spec.stage
                or candidate.spec.source_element_id != facility.spec.source_element_id
                or candidate.portal_entry_level_id != facility.portal_entry_level_id
            ):
                continue
            candidate_slots = model._facility_approach_slot_indices(candidate)
            candidate_ingress = (
                model._gate_queue_ingress_anchors(
                    passenger,
                    candidate,
                    int(candidate_slots[0]),
                )
                if candidate_slots
                else ()
            )
            if candidate_ingress:
                bank_mouths.append(candidate_ingress[-1])
        nearest_bank_tail_distance = min(
            (
                hypot(passenger.pos[0] - point[0], passenger.pos[1] - point[1])
                for point in bank_mouths
            ),
            default=float("inf"),
        )
        recovery_radius = max(
            float(model.scenario.jupedsim_target_radius_units),
            float(model.scenario.personal_space_units) * 2.0,
        )
        if nearest_bank_tail_distance > recovery_radius:
            return False
        next_target = model._facility_approach_slot_position(facility, int(slot_index))
        passenger.set_route(
            (next_target,),
            goal_kind="queue_approach",
            goal_label="gate tail stall recovery",
            facility_id=facility.facility_id,
            stage=stage,
        )
        model.audit.record(
            "passenger_advanced_stalled_gate_ingress_turn",
            source="goal_runtime",
            step=int(model.step_index),
            context={
                "passenger_id": int(passenger.unique_id),
                "facility_id": facility.facility_id,
                "stage": stage,
                "reason": reason,
                "mode": "exhausted_tail_route",
                "distance": float(distance_to_mouth),
                "nearest_bank_tail_distance": float(nearest_bank_tail_distance),
                "recovery_radius": recovery_radius,
                "reached_turn": [float(mouth[0]), float(mouth[1])],
                "next_target": [float(next_target[0]), float(next_target[1])],
            },
        )
        return True
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
