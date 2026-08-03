"""Testkit component migrated from the legacy runtime namespace."""

from __future__ import annotations

from math import hypot, pi

from metro_station.adapters.simulation.planning.goal_events import DecisionObservation, FacilityObservation
from .goal_stairs_fixture import CONCOURSE_LEVEL, PLATFORM_LEVEL
from .goal_stairs_micro_scene import GoalStairsMicroScene


def stairs_decision_observation(scene: GoalStairsMicroScene) -> DecisionObservation:
    candidates = []
    for stairs in scene.stairs:
        blockers = scene.blocker_count_near(
            stairs.spec.queue_anchor,
            1.2,
            level_id=CONCOURSE_LEVEL,
        )
        candidates.append(
            FacilityObservation(
                facility_id=stairs.facility_id,
                stage=stairs.spec.stage,
                available=stairs.facility_id not in scene.disabled_stair_ids,
                reachable=blockers < 4,
                walking_time_seconds=distance(
                    scene.subject.pos,
                    stairs.spec.queue_anchor,
                )
                / 1.2,
                queue_persons=stairs.queue_persons,
                estimated_wait_seconds=stairs.queue_persons
                / max(0.001, stairs.effective_service_persons_per_min)
                * 60,
                local_density_persons_m2=blockers / (pi * 1.2**2),
                service_state=stairs.state,
            )
        )
    return DecisionObservation(
        time_seconds=scene.current_time_seconds,
        current_region_id="vertical_decision",
        candidates=tuple(candidates),
    )


def stair_entrance_blocked(scene: GoalStairsMicroScene, facility_id: str) -> bool:
    stairs = scene.stairs_by_id[facility_id]
    blockers = scene.blocker_count_near(
        stairs.spec.queue_anchor,
        1.2,
        level_id=CONCOURSE_LEVEL,
    )
    return blockers >= 4 and distance(scene.subject.pos, stairs.spec.queue_anchor) <= 4.5


def platform_landing_blocked(scene: GoalStairsMicroScene) -> bool:
    return (
        scene.blocker_count_near(
            scene.platform_landing_position,
            1.5,
            level_id=PLATFORM_LEVEL,
        )
        >= 4
    )


def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return hypot(left[0] - right[0], left[1] - right[1])
