from __future__ import annotations

from abc import ABC, abstractmethod

import mesa


Point = tuple[float, float]


class StationAgent(mesa.Agent, ABC):
    """Base type for station entities owned by the Mesa model."""

    @abstractmethod
    def step(self) -> None:
        """Advance the station entity by one model tick."""


class MovableAgent(StationAgent, ABC):
    """Station entity with a continuous position and movement target."""

    pos: Point
    target: Point

    @abstractmethod
    def move_toward_target(self) -> bool:
        """Move toward the current target and return whether it was reached."""


class ServiceAgent(StationAgent, ABC):
    """Queueing/service facility that can accept movable agents."""

    @abstractmethod
    def join_queue(self, agent: MovableAgent) -> None:
        """Assign an agent to this facility queue."""

    @abstractmethod
    def _serve_queue(self, *args, **kwargs) -> None:
        """Release queued agents according to this facility's service rules."""
