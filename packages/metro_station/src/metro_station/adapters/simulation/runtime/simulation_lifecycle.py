from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..agents.passenger import PassengerAgent
from ..facilities.runtime import FacilityProcessAgent
from ..movement.backend import MovementResult


class SimulationLifecycleMixin:
    """Expose run/step lifecycle, stopping, evidence frames, and snapshots."""

    def step(self) -> None:
        self.step_orchestrator.step(self)

    def _capture_spawn_evidence_frame(self) -> None:
        if not self._spawned_since_last_frame:
            return
        self.rebuild_spatial_index()
        frame = self.snapshot()
        if self.frames and self.frames[-1]["step"] == frame["step"]:
            # A regular frame already represents this simulation boundary. Spawn
            # evidence belongs to that same instant, so refresh the boundary
            # instead of creating a second trajectory sample at the same time.
            self.frames[-1] = frame
        else:
            self.frames.append(frame)
        self._spawned_since_last_frame = False

    def _sync_facility_queue_layouts_for_snapshot(self) -> None:
        for facility in self.facilities:
            if isinstance(facility, FacilityProcessAgent) and facility.queue:
                facility._layout_queue()

    def _intercept_facility_queue_crossing(
        self,
        passenger: PassengerAgent,
        result: MovementResult,
    ) -> MovementResult:
        if result.reached:
            return result
        goal = passenger.current_goal
        if goal.facility_id is None:
            return result
        facility = self.facilities_by_id.get(goal.facility_id)
        if not isinstance(facility, FacilityProcessAgent):
            return result
        if goal.stage != facility.spec.stage:
            return result

        # Keep the crossing guard tied to the target that produced this
        # movement episode.  Recomputing the "currently available" queue slot
        # here can change underneath an in-flight agent and snap it to a
        # different lane when another passenger joins or leaves the queue.
        queue_target = self.clamp_position(
            goal.target
            if goal.target is not None
            else self._facility_queue_approach_target(passenger, facility)
        )
        return facility.intercept_queue_approach_crossing(result, queue_target)

    def _should_stop(self) -> bool:
        if self.step_index >= self.scenario.horizon_steps:
            return True
        return (
            self.step_index >= self.scenario.demand_steps
            and not self.passengers
            and not self._has_pending_alighting_demand()
            and not any(self.pending_spawn_groups.values())
            and not self.disruption_controller.has_pending_events
            and not self.train_disruption_controller.has_pending_events
            and not self.control_timeline_controller.has_pending_events
        )

    def _has_pending_alighting_demand(self) -> bool:
        if self.pending_alighting_groups > 0:
            return True
        return any(
            step >= self.step_index and count > 0 for step, count in self.alighting_schedule.items()
        )

    def run(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[dict[str, Any]]:
        self.running = True
        total_steps = int(self.scenario.horizon_steps)
        if progress_callback is not None:
            progress_callback(self.step_index, total_steps)
        while self.running:
            self.step()
            if progress_callback is not None:
                progress_callback(self.step_index, total_steps)
        self._finalize_facilities()
        return self.frames

    def _finalize_facilities(self) -> None:
        for facility in self.facilities:
            finalize = getattr(facility, "finalize", None)
            if not callable(finalize):
                continue
            finalize()
        if self.frames:
            previous_control_events = self.frames[-1].get("control_events", [])
            final_snapshot = self.snapshot()
            if previous_control_events and not final_snapshot.get("control_events"):
                final_snapshot["control_events"] = previous_control_events
            self.frames[-1] = final_snapshot

    def snapshot(
        self,
        *,
        control_event_time_seconds: float | None = None,
    ) -> dict[str, Any]:
        payload = self.snapshot_builder.build(
            self,
            control_event_time_seconds=control_event_time_seconds,
        ).to_dict()
        payload["goal_graph_parity"] = self.goal_parity.report(
            self,
            include_events=False,
        )
        return payload
