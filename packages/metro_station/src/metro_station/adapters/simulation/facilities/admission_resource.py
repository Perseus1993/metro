from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AdmissionResidence:
    owner_id: Hashable
    acquired_step: int
    released_step: int
    release_reason: str

    @property
    def residence_steps(self) -> int:
        return self.released_step - self.acquired_step

    @property
    def right_censored(self) -> bool:
        return self.release_reason == "lifecycle_right_censored"


@dataclass
class AdmissionTokenResource:
    """Finite flow-control credits with no physical or geometric ownership.

    The resource answers only whether another upstream group may enter a flow.
    Body placement and collision exclusion remain responsibilities of the
    movement backend at the publication boundary.
    """

    resource_id: str
    capacity: int
    _acquired_step_by_owner_id: dict[Hashable, int] = field(default_factory=dict)
    completed_residences: list[AdmissionResidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.capacity, int) or isinstance(self.capacity, bool):
            raise TypeError("admission token capacity must be an integer")
        if self.capacity <= 0:
            raise ValueError("admission token capacity must be positive")

    @property
    def available(self) -> int:
        return self.capacity - len(self._acquired_step_by_owner_id)

    @property
    def occupancy(self) -> int:
        return len(self._acquired_step_by_owner_id)

    @property
    def owners(self) -> tuple[Hashable, ...]:
        return tuple(self._acquired_step_by_owner_id)

    def active_residence_steps(self, step: int) -> list[int]:
        """Return lower-bound residence ages for right-censored owners."""

        current_step = int(step)
        ages = [
            current_step - acquired_step
            for acquired_step in self._acquired_step_by_owner_id.values()
        ]
        if any(age < 0 for age in ages):
            raise RuntimeError("admission token observation precedes acquisition")
        return ages

    def acquire(self, owner_id: Hashable, step: int) -> bool:
        if owner_id in self._acquired_step_by_owner_id:
            raise RuntimeError(
                f"admission token {self.resource_id!r} is already owned by {owner_id!r}"
            )
        if self.available <= 0:
            return False
        self._acquired_step_by_owner_id[owner_id] = int(step)
        return True

    def transfer(self, previous_owner_id: Hashable, next_owner_id: Hashable) -> None:
        if previous_owner_id not in self._acquired_step_by_owner_id:
            raise RuntimeError(
                f"admission token {self.resource_id!r} has no owner {previous_owner_id!r}"
            )
        if next_owner_id in self._acquired_step_by_owner_id:
            raise RuntimeError(
                f"admission token {self.resource_id!r} already has owner {next_owner_id!r}"
            )
        acquired_step = self._acquired_step_by_owner_id.pop(previous_owner_id)
        self._acquired_step_by_owner_id[next_owner_id] = acquired_step

    def release(
        self,
        owner_id: Hashable,
        step: int,
        *,
        reason: str,
    ) -> AdmissionResidence:
        if owner_id not in self._acquired_step_by_owner_id:
            raise RuntimeError(
                f"admission token {self.resource_id!r} cannot double-release "
                f"unknown owner {owner_id!r}"
            )
        acquired_step = self._acquired_step_by_owner_id.pop(owner_id)
        released_step = int(step)
        if released_step < acquired_step:
            raise RuntimeError("admission token release precedes acquisition")
        residence = AdmissionResidence(
            owner_id=owner_id,
            acquired_step=acquired_step,
            released_step=released_step,
            release_reason=str(reason),
        )
        self.completed_residences.append(residence)
        return residence

    def close(self, step: int) -> list[AdmissionResidence]:
        """Close every active owner as right-censored lifecycle evidence."""

        return [
            self.release(
                owner_id,
                step,
                reason="lifecycle_right_censored",
            )
            for owner_id in self.owners
        ]


__all__ = ["AdmissionResidence", "AdmissionTokenResource"]
