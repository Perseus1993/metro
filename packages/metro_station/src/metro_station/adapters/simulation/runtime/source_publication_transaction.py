from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from ..agents.passenger import PassengerAgent

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


class PassengerPublicationTransaction:
    """Make Passenger construction and publication atomic to the model."""

    def __init__(self, model: MetroStationModel) -> None:
        self.model = model
        self._agent_id_counter = int(model.agent_id_counter)
        self._random_state = model.random.getstate()
        self._rng_state = deepcopy(model.rng.bit_generator.state)
        self._spawned_persons = int(model.spawned_persons)
        self._spawned_persons_by_intent = model.spawned_persons_by_intent.copy()
        self._spawned_persons_by_entrance = model.spawned_persons_by_entrance.copy()
        self._spawned_since_last_frame = bool(model._spawned_since_last_frame)
        self._goal_parity_event_count = len(model.goal_parity.events)
        self._facility_choice_log_count = len(model.facility_choice_decision_logs)
        self._audit_event_count = len(model.audit.events)
        self._audit_counts = model.audit.counts.copy()
        self._audit_once_keys = set(model.audit._once_keys)
        self._service_chain_event_counts = model.service_chain_event_counts.copy()
        self._committed = False

    def __enter__(self) -> PassengerPublicationTransaction:
        return self

    def commit(self) -> None:
        self._committed = True

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc, traceback
        if self._committed:
            return False
        self._rollback()
        if exc_type is None:
            raise RuntimeError("passenger publication transaction exited without commit")
        return False

    def _rollback(self) -> None:
        new_agents = [
            agent
            for agent in tuple(self.model.agents)
            if int(agent.unique_id) >= self._agent_id_counter
        ]
        for agent in reversed(new_agents):
            if isinstance(agent, PassengerAgent):
                rollback_published_passenger(self.model, agent)
                continue
            agent.remove()

        self.model.spawned_persons = self._spawned_persons
        self.model.spawned_persons_by_intent.clear()
        self.model.spawned_persons_by_intent.update(self._spawned_persons_by_intent)
        self.model.spawned_persons_by_entrance.clear()
        self.model.spawned_persons_by_entrance.update(self._spawned_persons_by_entrance)
        self.model._spawned_since_last_frame = self._spawned_since_last_frame
        del self.model.goal_parity.events[self._goal_parity_event_count :]
        del self.model.facility_choice_decision_logs[self._facility_choice_log_count :]
        del self.model.audit.events[self._audit_event_count :]
        self.model.audit.counts.clear()
        self.model.audit.counts.update(self._audit_counts)
        self.model.audit._once_keys.clear()
        self.model.audit._once_keys.update(self._audit_once_keys)
        self.model.service_chain_event_counts.clear()
        self.model.service_chain_event_counts.update(self._service_chain_event_counts)
        for passenger_id in tuple(self.model.goal_coordinator._command_sequences):
            if int(passenger_id) >= self._agent_id_counter:
                self.model.goal_coordinator._command_sequences.pop(passenger_id, None)
        self.model.agent_id_counter = self._agent_id_counter
        self.model.random.setstate(self._random_state)
        self.model.rng.bit_generator.state = deepcopy(self._rng_state)


def rollback_published_passenger(
    model: MetroStationModel,
    passenger: PassengerAgent,
) -> None:
    """Compensate a Passenger published before its source commit completed."""

    clear_facility = getattr(model, "_clear_all_facility_targeting_reservations", None)
    if callable(clear_facility) and hasattr(passenger, "facility_approach_slots_by_stage"):
        clear_facility(passenger)
    clear_holding = getattr(model, "_clear_all_decision_holding_reservations", None)
    if callable(clear_holding) and hasattr(passenger, "decision_holding_target_by_region"):
        clear_holding(passenger)
    remove_holding = getattr(model, "_remove_from_station_holding_areas", None)
    if callable(remove_holding) and hasattr(passenger, "assigned_platform_id"):
        remove_holding(passenger)
    if getattr(passenger, "unique_id", None) is not None:
        model.movement_backend.remove_passenger(passenger)
    was_published = passenger in model.passengers
    try:
        model.passengers.remove(passenger)
    except ValueError:
        pass
    passenger_id = getattr(passenger, "unique_id", None)
    if passenger_id is not None:
        model.passenger_goal_runtimes.pop(int(passenger_id), None)
    if was_published:
        group_size = int(passenger.group_size)
        model.spawned_persons -= group_size
        model.spawned_persons_by_intent[passenger.intent] -= group_size
        if passenger.spawn_source_element_id is not None:
            model.spawned_persons_by_entrance[passenger.spawn_source_element_id] -= group_size
    passenger.remove()


__all__ = ["PassengerPublicationTransaction", "rollback_published_passenger"]
