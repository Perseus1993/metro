from __future__ import annotations

from ..agents.passenger import PassengerAgent
from ..facilities.runtime import FacilityProcessAgent
from ..planning.plan import AgentIntent, AgentState
from .terminal_events import PassengerTerminalEvent


class PassengerDepartureMixin:
    """Commit Goal-authorized terminal events and remove passengers exactly once."""

    def complete_departure(
        self,
        passenger: PassengerAgent,
        *,
        boarded: bool = True,
        goal_authorized: bool = False,
    ) -> None:
        if not goal_authorized:
            return
        if passenger.state == AgentState.DEPARTED.value:
            return
        self._clear_all_facility_targeting_reservations(passenger)
        self.movement_backend.remove_passenger(passenger)
        self._remove_from_station_holding_areas(passenger)
        passenger.state = AgentState.DEPARTED.value
        passenger.boarded_step = self.step_index
        minutes = (self.step_index - passenger.created_step) * self.scenario.tick_seconds / 60.0
        self.departed_wait_minutes.append(minutes)
        completion_time_seconds = (self.step_index + 1) * self.scenario.tick_seconds
        duration_seconds = (
            self.step_index + 1 - passenger.created_step
        ) * self.scenario.tick_seconds
        terminal_event = "boarded_train" if boarded else "left_station"
        if passenger.intent == AgentIntent.EVACUATE_STATION.value:
            terminal_event = "reached_safe_zone"
            self.evacuated_persons += passenger.group_size
        self.departed_persons += passenger.group_size
        self.passenger_terminal_events.append(
            PassengerTerminalEvent(
                passenger_id=int(passenger.unique_id),
                intent=str(passenger.intent),
                event=terminal_event,
                time_seconds=float(completion_time_seconds),
                duration_seconds=float(duration_seconds),
                persons=int(passenger.group_size),
            )
        )
        self.goal_parity.record(
            passenger,
            stream="physical",
            kind="terminal_reached",
            time_seconds=float(completion_time_seconds),
            node_id=passenger.goal_runtime.state.current_node_id,
            reason=terminal_event,
        )
        if boarded:
            self.boarded_persons += passenger.group_size
        try:
            self.passengers.remove(passenger)
        except ValueError:
            self.audit.record(
                "passenger_remove_missing",
                source="mesa_model",
                severity="error",
                step=self.step_index,
                context={
                    "passenger_id": passenger.unique_id,
                    "state": passenger.state,
                    "boarded": boarded,
                },
            )
        passenger.remove()

    def _remove_from_station_holding_areas(self, passenger: PassengerAgent) -> None:
        for platform in self.platforms:
            platform.waiting = [waiting for waiting in platform.waiting if waiting is not passenger]
        for facility in self.facilities:
            if isinstance(facility, FacilityProcessAgent):
                facility.queue.discard(passenger)
