from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

from ..planning.plan import AgentIntent, FacilityStage


class FacilitySpecLike(Protocol):
    entry_level_id: str | None
    platform_id: str | None
    line_id: str
    direction: str


class FacilityLike(Protocol):
    spec: FacilitySpecLike


class PlatformLike(Protocol):
    platform_id: str
    line_id: str
    direction: str


class PassengerLike(Protocol):
    current_level_id: str | None
    assigned_platform_id: str | None
    assigned_line_id: str | None
    assigned_direction: str | None
    target_line_id: str | None
    target_direction: str | None
    intent: str


F = TypeVar("F", bound=FacilityLike)
P = TypeVar("P", bound=PlatformLike)


def filter_by_current_level(
    passenger: PassengerLike,
    candidates: Sequence[F],
    *,
    strict: bool = False,
) -> list[F]:
    level_id = passenger.current_level_id
    if level_id is None:
        return list(candidates)

    matching = [
        item
        for item in candidates
        if item.spec.entry_level_id is None or item.spec.entry_level_id == level_id
    ]
    if strict:
        return matching
    return matching or list(candidates)


def filter_boarding_doors_for_passenger(
    passenger: PassengerLike,
    candidates: Sequence[F],
) -> list[F]:
    platform_id = passenger.assigned_platform_id
    if platform_id is not None:
        return [item for item in candidates if item.spec.platform_id == platform_id]

    filtered = list(candidates)
    line_id = passenger.assigned_line_id
    direction = passenger.assigned_direction
    if line_id is not None:
        filtered = [item for item in filtered if item.spec.line_id == line_id]
    if direction is not None:
        filtered = [item for item in filtered if item.spec.direction == direction]
    return filtered


def filter_boarding_doors_for_platform(
    platform: PlatformLike,
    candidates: Sequence[F],
) -> list[F]:
    return [
        door
        for door in candidates
        if door.spec.platform_id == platform.platform_id
        or (
            door.spec.platform_id is None
            and door.spec.line_id == platform.line_id
            and door.spec.direction == platform.direction
        )
    ]


def filter_vertical_transfers_for_passenger(
    passenger: PassengerLike,
    candidates: Sequence[F],
) -> list[F]:
    direction = "up" if passenger.intent == AgentIntent.EXIT_STATION.value else "down"
    return [item for item in candidates if item.spec.direction in {direction, "both"}]


def filter_facilities_for_passenger(
    passenger: PassengerLike,
    stage: str | FacilityStage,
    candidates: Sequence[F],
) -> list[F]:
    stage_value = stage.value if isinstance(stage, FacilityStage) else str(stage)
    strict_level = stage_value in {
        FacilityStage.VERTICAL_TRANSFER.value,
        FacilityStage.BOARDING_DOOR.value,
    }
    filtered = filter_by_current_level(passenger, candidates, strict=strict_level)
    if stage_value == FacilityStage.BOARDING_DOOR.value:
        filtered = filter_boarding_doors_for_passenger(passenger, filtered)
    elif stage_value == FacilityStage.VERTICAL_TRANSFER.value:
        filtered = filter_vertical_transfers_for_passenger(passenger, filtered)
    return filtered


def filter_platforms_for_passenger(passenger: PassengerLike, candidates: Sequence[P]) -> list[P]:
    filtered = list(candidates)
    if passenger.target_line_id is not None:
        matching = [
            platform for platform in filtered if platform.line_id == passenger.target_line_id
        ]
        if not matching:
            return []
        filtered = matching
    if passenger.target_direction is not None:
        matching = [
            platform for platform in filtered if platform.direction == passenger.target_direction
        ]
        if not matching:
            return []
        filtered = matching
    return filtered
