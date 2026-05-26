from __future__ import annotations

from dataclasses import dataclass

from ..floor_field import GridDistanceField
from ..queue_runtime import NativeQueueRuntime


@dataclass(frozen=True)
class StageInfo:
    stage_id: int
    kind: str
    label: str
    point_m: tuple[float, float] | None = None
    radius_m: float | None = None
    slots_m: tuple[tuple[float, float], ...] = ()
    facility: str | None = None
    journey: str | None = None


StageRegistry = dict[int, StageInfo]
SoftReleaseTargets = dict[tuple[int, int], tuple[int, ...]]
StageAdvanceTargets = dict[tuple[int, int], tuple[int, ...]]
QueueReplanTargets = dict[tuple[int, int], tuple[int, ...]]
QueueDistanceFields = dict[int, GridDistanceField]


@dataclass
class AgentProgress:
    stage_id: int
    journey_id: int
    position: tuple[float, float]
    last_progress_time: float


@dataclass(frozen=True)
class ServiceRelease:
    runtime: NativeQueueRuntime
    sim_id: int
    mode: str
    release_reachable: bool | None = None
    release_stage_id: int | None = None


@dataclass(frozen=True)
class WaypointBandChain:
    bands: tuple[tuple[int, ...], ...]

    @property
    def first_stage_id(self) -> int:
        return self.bands[0][0]

    @property
    def first_band(self) -> tuple[int, ...]:
        return self.bands[0]

    @property
    def last_band(self) -> tuple[int, ...]:
        return self.bands[-1]

    @property
    def stage_ids(self) -> tuple[int, ...]:
        return tuple(stage_id for band in self.bands for stage_id in band)


@dataclass(frozen=True)
class EntryJourneyRuntime:
    name: str
    color: str
    weight: int
    start: tuple[float, float]
    journey_id: int
    first_stage_id: int


@dataclass(frozen=True)
class ArrivalSlot:
    time: float
    entry: EntryJourneyRuntime
    group_id: int
    member_index: int
    group_size: int
    speed_base: float
