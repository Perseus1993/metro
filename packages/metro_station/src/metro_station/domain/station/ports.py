from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class StationRegionRef:
    region_id: str
    level_id: str


@dataclass(frozen=True)
class StationFacilityRef:
    facility_id: str
    stage: str
    entry_region_id: str
    exit_region_id: str
    decision_region_id: str


@runtime_checkable
class StationGraphPort(Protocol):
    """Static station-topology view required by the Goal domain."""

    def has_region(self, region_id: str) -> bool: ...

    def decision_region_for_stage(
        self,
        stage: str,
        *,
        origin_region_id: str | None = None,
    ) -> str | None: ...

    def facilities_for_stage(
        self,
        stage: str,
        *,
        level_id: str | None = None,
    ) -> tuple[StationFacilityRef, ...]: ...

    def vertical_transfer_count_for_intent(self, intent: str) -> int: ...


@runtime_checkable
class JourneyTopologyPort(Protocol):
    """Minimal topology capability required to compile an intent catalog."""

    def vertical_transfer_count_for_intent(self, intent: str) -> int: ...
