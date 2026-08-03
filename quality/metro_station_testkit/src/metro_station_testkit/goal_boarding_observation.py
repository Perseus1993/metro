"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from math import hypot, pi

from metro_station.adapters.simulation.planning.goal_events import DecisionObservation, FacilityObservation
from .goal_boarding_micro_scene import GoalBoardingMicroScene


def boarding_decision_observation(scene: GoalBoardingMicroScene) -> DecisionObservation:
    candidates = []
    train_full = scene.train.is_boarding and scene.train.capacity_remaining < 1
    for door in scene.doors:
        blockers = scene.blocker_count_near(door.spec.queue_anchor, 1.2)
        candidates.append(
            FacilityObservation(
                facility_id=door.facility_id,
                stage=door.spec.stage,
                available=door.facility_id not in scene.disabled_door_ids,
                reachable=blockers < 4 and not train_full,
                walking_time_seconds=distance(
                    scene.subject.pos,
                    door.spec.queue_anchor,
                )
                / 1.2,
                queue_persons=door.queue_persons,
                estimated_wait_seconds=_estimated_wait_seconds(scene, door.queue_persons),
                local_density_persons_m2=blockers / (pi * 1.2**2),
                service_state=door.state,
            )
        )
    return DecisionObservation(
        time_seconds=scene.current_time_seconds,
        current_region_id="boarding_decision",
        candidates=tuple(candidates),
    )


def door_front_blocked(scene: GoalBoardingMicroScene, facility_id: str) -> bool:
    door = scene.doors_by_id[facility_id]
    blockers = scene.blocker_count_near(door.spec.queue_anchor, 1.2)
    return blockers >= 4 and distance(scene.subject.pos, door.spec.queue_anchor) <= 4.5


def _estimated_wait_seconds(scene: GoalBoardingMicroScene, queue_persons: int) -> float:
    queue_wait = queue_persons / 240.0 * 60.0
    if scene.train.is_boarding:
        return queue_wait
    until_arrival_steps = max(0, scene.train.next_arrival_step - scene.step_index)
    return queue_wait + until_arrival_steps * scene.scenario.tick_seconds


def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])
