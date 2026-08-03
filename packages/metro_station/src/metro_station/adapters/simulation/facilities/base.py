from __future__ import annotations

from typing import TYPE_CHECKING

import mesa

from ..agents.base import StationAgent
from .process import FacilitySpec

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent


class FacilityAgent(StationAgent):
    """Base runtime object for station facilities with or without service flow."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model)
        self.spec = spec
        self.facility_id = spec.facility_id
        self.state = "idle"
        self._served_persons = 0

    @property
    def is_open(self) -> bool:
        return not self.is_forced_disabled and self.state not in {"blocked", "closed", "idle"}

    @property
    def is_forced_disabled(self) -> bool:
        runtime_check = getattr(self.model, "is_facility_disabled", None)
        if callable(runtime_check):
            return bool(runtime_check(self.facility_id))
        disabled = getattr(self.model.scenario, "disabled_facility_ids", ())
        return self.facility_id in disabled

    @property
    def is_running(self) -> bool:
        return self.is_open

    @property
    def is_available_for_choice(self) -> bool:
        return self.is_open

    @property
    def queue_persons(self) -> int:
        return 0

    @property
    def served_persons(self) -> int:
        return self._served_persons

    @served_persons.setter
    def served_persons(self, value: int) -> None:
        self._served_persons = int(value)

    @property
    def effective_service_persons_per_min(self) -> float:
        return 0.0

    def has_active_service(self, passenger: PassengerAgent) -> bool:
        return False

    def on_availability_changed(
        self,
        *,
        disabled: bool,
        time_seconds: float,
    ) -> None:
        return None

    def step(self, train: object | None = None) -> None:
        return None


class AmenityFacilityAgent(FacilityAgent):
    """Non-service facility placeholder for amenities and static interactions."""

    def __init__(self, model: mesa.Model, *, spec: FacilitySpec) -> None:
        super().__init__(model, spec=spec)
        self.state = "active"

    @property
    def is_open(self) -> bool:
        return not self.is_forced_disabled and self.state == "active"
