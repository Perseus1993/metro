"""Framework-independent simulation execution use case."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


ScenarioT = TypeVar("ScenarioT")
FrameT = TypeVar("FrameT")
RuntimeT = TypeVar("RuntimeT")
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class SimulationRequest(Generic[ScenarioT]):
    scenario: ScenarioT
    seed: int = 42


@dataclass(frozen=True)
class SimulationExecutionResult(Generic[FrameT, RuntimeT]):
    frames: list[FrameT]
    runtime: RuntimeT


class SimulationExecutor(Protocol[ScenarioT, FrameT, RuntimeT]):
    def execute(
        self,
        request: SimulationRequest[ScenarioT],
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> SimulationExecutionResult[FrameT, RuntimeT]: ...


def run_simulation(
    request: SimulationRequest[ScenarioT],
    executor: SimulationExecutor[ScenarioT, FrameT, RuntimeT],
    *,
    progress_callback: ProgressCallback | None = None,
) -> SimulationExecutionResult[FrameT, RuntimeT]:
    """Execute one simulation without exposing a concrete framework to callers."""

    return executor.execute(request, progress_callback=progress_callback)
