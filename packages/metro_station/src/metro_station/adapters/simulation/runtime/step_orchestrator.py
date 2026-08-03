from __future__ import annotations

from typing import TYPE_CHECKING

from ..station.evacuation import EVACUATION_MODE

if TYPE_CHECKING:
    from .mesa_model import MetroStationModel


class SimulationStepOrchestrator:
    """Execute one simulation tick in the compatibility-critical phase order."""

    def step(self, model: MetroStationModel) -> None:
        interval_start_time_seconds = model.current_time_seconds
        model.train_disruption_controller.apply_due(model)
        model.control_timeline_controller.apply_due(model)
        model.disruption_controller.apply_due(model)
        model.control_timeline_controller.capture_facility_results(model)
        model._activate_evacuation_if_due()
        model.spawn_passengers()
        model.evacuation_routing.raise_if_failed()
        for passenger in tuple(model.passengers):
            model.goal_coordinator.poll(passenger)
        model.evacuation_routing.raise_if_failed()

        if not self._evacuation_stops_trains(model):
            for train in model.trains:
                train.step()
            model.spawn_alighting_passengers()

        model._rebalance_current_step_approach_slots()
        model._capture_spawn_evidence_frame()
        for facility_group in (
            model.gates,
            model.exit_gates,
            model.vertical_transports,
            model.platforms,
        ):
            for facility in facility_group:
                facility.step()
        for door in model.boarding_doors:
            door.step(model.train_for_facility(door))
        # Platform polling happens before door service so waiting passengers can
        # claim this train.  Publish the post-allocation state as a second phase:
        # when several queues observed the same last seats, passengers left in
        # those queues must receive TRAIN_FULL before the train departs.
        for door in model.boarding_doors:
            for passenger in tuple(door.queue):
                model.goal_coordinator.poll(passenger)
        for admin in model.admin_agents:
            admin.step()

        model.rebuild_spatial_index()
        for passenger, movement_result in model.movement_backend.step_all(list(model.passengers)):
            movement_result = model.control_timeline_controller.constrain_movement(
                model,
                passenger,
                movement_result,
            )
            movement_result = model._constrain_movement_to_dynamic_bodies(
                passenger,
                movement_result,
            )
            movement_result = model._intercept_facility_queue_crossing(
                passenger,
                movement_result,
            )
            reached = passenger.apply_movement_result(movement_result)
            passenger.advance_after_movement(reached)
        model.progress_monitor.observe(model, list(model.passengers))

        model.rebuild_spatial_index()
        # The work above advances the simulation across [step, step + 1].
        # Publish its resulting state at the interval end, not at the start.
        model.step_index += 1
        model.datacollector.collect(model)
        model.frames.append(
            model.snapshot(control_event_time_seconds=interval_start_time_seconds)
        )
        if model._should_stop():
            model.running = False

    @staticmethod
    def _evacuation_stops_trains(model: MetroStationModel) -> bool:
        return (
            model.scenario.scenario_mode == EVACUATION_MODE
            and model.scenario.evacuation is not None
            and model.scenario.evacuation.stop_train_service
        )
