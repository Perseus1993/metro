"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from math import hypot, pi

from metro_station.adapters.simulation.planning.goal_events import DecisionObservation, FacilityObservation
from metro_station.adapters.simulation.planning.plan import FacilityStage
from .goal_journey_micro_scene import GoalJourneyMicroScene


DECISION_REGION_BY_STAGE = {
    FacilityStage.ENTRY_GATE.value: "entry_gate_decision",
    FacilityStage.VERTICAL_TRANSFER.value: "vertical_decision",
    FacilityStage.BOARDING_DOOR.value: "boarding_decision",
}


def journey_decision_observation(
    scene: GoalJourneyMicroScene,
    stage: str,
) -> DecisionObservation:
    candidates = []
    for facility in facilities_for_stage(scene, stage):
        blockers = blocker_count(scene, facility)
        candidates.append(
            FacilityObservation(
                facility_id=facility.facility_id,
                stage=facility.spec.stage,
                available=not facility_disabled(scene, facility.facility_id, stage),
                reachable=blockers < 4 and not _train_full(scene, stage),
                walking_time_seconds=distance(
                    scene.subject.pos,
                    facility.spec.queue_anchor,
                )
                / 1.2,
                queue_persons=facility.queue_persons,
                estimated_wait_seconds=_estimated_wait(scene, facility, stage),
                local_density_persons_m2=blockers / (pi * 1.2**2),
                service_state=facility.state,
            )
        )
    return DecisionObservation(
        time_seconds=scene.current_time_seconds,
        current_region_id=DECISION_REGION_BY_STAGE[stage],
        candidates=tuple(candidates),
    )


def facilities_for_stage(scene: GoalJourneyMicroScene, stage: str):
    return [item for item in scene.facilities if item.spec.stage == stage]


def facility_disabled(scene: GoalJourneyMicroScene, facility_id: str, stage: str) -> bool:
    disabled = {
        FacilityStage.ENTRY_GATE.value: scene.disabled_gate_ids,
        FacilityStage.VERTICAL_TRANSFER.value: scene.disabled_stair_ids,
        FacilityStage.BOARDING_DOOR.value: scene.disabled_door_ids,
    }[stage]
    return facility_id in disabled


def blocker_count(scene: GoalJourneyMicroScene, facility) -> int:
    return scene.blocker_count_near(
        facility.spec.queue_anchor,
        1.2,
        level_id=str(facility.spec.entry_level_id),
    )


def facility_path_blocked(scene: GoalJourneyMicroScene, facility) -> bool:
    return blocker_count(scene, facility) >= 4 and distance(
        scene.subject.pos,
        facility.spec.queue_anchor,
    ) <= 4.5


def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])


def _estimated_wait(scene: GoalJourneyMicroScene, facility, stage: str) -> float:
    wait = facility.queue_persons / max(0.001, facility.effective_service_persons_per_min) * 60
    if stage != FacilityStage.BOARDING_DOOR.value or scene.train.is_boarding:
        return wait
    until_train = max(0, scene.train.next_arrival_step - scene.step_index)
    return wait + until_train * scene.scenario.tick_seconds


def _train_full(scene: GoalJourneyMicroScene, stage: str) -> bool:
    return (
        stage == FacilityStage.BOARDING_DOOR.value
        and scene.train.is_boarding
        and scene.train.capacity_remaining < 1
    )
