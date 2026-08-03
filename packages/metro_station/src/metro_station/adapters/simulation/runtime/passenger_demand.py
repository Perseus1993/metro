from __future__ import annotations

from collections import Counter
from math import hypot

from ..agents.passenger import PassengerAgent
from ..agents.transit import TrainAgent
from ..facilities.runtime import FacilityProcessAgent
from ..planning.goal_events import GoalEventKind
from ..planning.plan import AgentIntent, FacilityStage
from ..station.evacuation import EVACUATION_MODE
from ..station.geometry import project_to_safe_point


class PassengerDemandMixin:
    """Scheduled passenger creation, alighting distribution, and evacuation conversion."""

    def spawn_passengers(self) -> None:
        due_by_intent = self.demand_scheduler.due_by_intent(self.step_index)
        for intent, count in due_by_intent.items():
            for _ in range(count):
                self._spawn_passenger(intent)

    def spawn_alighting_passengers(self) -> None:
        newly_due = self.demand_scheduler.due_alightings(self.step_index)
        due = self.pending_alighting_groups + newly_due
        if due <= 0:
            return

        boarding_trains = [train for train in self.trains if train.is_boarding]
        if not boarding_trains:
            self.pending_alighting_groups = due
            self.max_pending_alighting_groups = max(
                self.max_pending_alighting_groups,
                self.pending_alighting_groups,
            )
            self.audit.record(
                "alighting_demand_deferred_without_boarding_train",
                source="demand_scheduler",
                severity="warning",
                step=self.step_index,
                context={
                    "newly_due_groups": newly_due,
                    "pending_groups": self.pending_alighting_groups,
                },
            )
            return

        self.pending_alighting_groups = 0
        for train, count in zip(
            boarding_trains,
            self._split_count(due, len(boarding_trains)),
            strict=True,
        ):
            self._spawn_alighting_passengers_for_train(train, count)

    def _spawn_passenger(
        self,
        intent: str | AgentIntent,
        *,
        initial_position: tuple[float, float] | None = None,
        initial_level_id: str | None = None,
    ) -> PassengerAgent:
        target_line_id = None
        target_direction = None
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        if intent_value == AgentIntent.TRANSFER.value:
            target_line_id, target_direction = self._default_transfer_target()
        passenger = PassengerAgent(
            self,
            group_size=self.scenario.group_size,
            created_step=self.step_index,
            intent=intent,
            target_line_id=target_line_id,
            target_direction=target_direction,
            initial_position=initial_position,
            initial_level_id=initial_level_id,
        )
        self.passengers.append(passenger)
        self.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
        self.spawned_persons += passenger.group_size
        self.spawned_persons_by_intent[passenger.intent] += passenger.group_size
        if passenger.spawn_source_element_id is not None:
            self.spawned_persons_by_entrance[passenger.spawn_source_element_id] += (
                passenger.group_size
            )
        self._spawned_since_last_frame = True
        return passenger

    def _default_transfer_target(self) -> tuple[str | None, str | None]:
        if not self.platforms:
            return None, None
        platform = sorted(
            self.platforms,
            key=lambda item: (item.line_id, item.direction, item.platform_id),
        )[0]
        return platform.line_id, platform.direction

    def _activate_evacuation_if_due(self) -> None:
        if self.scenario.scenario_mode != EVACUATION_MODE or self._evacuation_activated:
            return
        assert self.scenario.evacuation is not None
        if self.step_index < self.scenario.evacuation.alarm_step(self.scenario.tick_seconds):
            return
        self._evacuation_activated = True
        for passenger in tuple(self.passengers):
            if passenger.intent == AgentIntent.EVACUATE_STATION.value:
                continue
            if self.passenger_has_active_facility_service(passenger):
                passenger.evacuation_pending = True
                continue
            self._activate_passenger_evacuation(passenger)

    def _activate_passenger_evacuation(
        self,
        passenger: PassengerAgent,
        *,
        completed_facility_id: str | None = None,
    ) -> None:
        station_interior = self._passenger_is_inside_station_for_alarm(
            passenger,
            completed_facility_id=completed_facility_id,
        )
        # Compile first.  If the physical topology is invalid, do not partially
        # release queues or replace the passenger's still-auditable runtime.
        evacuation_runtime = self.evacuation_goal_runtime_from_position(
            passenger,
            station_interior=station_interior,
        )
        self._remove_from_station_holding_areas(passenger)
        self._clear_all_facility_targeting_reservations(passenger)
        passenger.evacuation_pending = False
        passenger.intent = AgentIntent.EVACUATE_STATION.value
        passenger.plan = self.plan_for_intent(AgentIntent.EVACUATE_STATION)
        passenger.goal_runtime = evacuation_runtime
        passenger.assigned_facility_id = None
        passenger.assigned_platform_id = None
        passenger.assigned_line_id = None
        passenger.assigned_direction = None
        self.passenger_goal_runtimes[int(passenger.unique_id)] = passenger.goal_runtime
        self.goal_coordinator.initialize(passenger)

    def refresh_evacuation_routes_for_topology_change(
        self,
        changed_facility_ids: set[str] | frozenset[str] = frozenset(),
        *,
        force_all: bool = False,
    ) -> int:
        """Re-root exact evacuation paths invalidated by availability or direction."""

        disabled_ids = {
            facility.facility_id
            for facility in self.facilities
            if isinstance(facility, FacilityProcessAgent)
            and facility.is_forced_disabled
        }
        refreshed = 0
        for passenger in tuple(self.passengers):
            path = tuple(passenger.evacuation_facility_path)
            if (
                passenger.intent != AgentIntent.EVACUATE_STATION.value
                or (
                    not force_all
                    and (
                        not path
                        or not (
                            disabled_ids.intersection(path)
                            or changed_facility_ids.intersection(path)
                        )
                    )
                )
            ):
                continue
            if self.passenger_has_active_facility_service(passenger):
                # Preserve the physical service.  Its completion callback will
                # re-root from the actual release level and position.
                passenger.evacuation_pending = True
                refreshed += 1
                continue
            self._activate_passenger_evacuation(passenger)
            refreshed += 1
        return refreshed

    def refresh_evacuation_routes_for_availability_change(
        self,
        changed_facility_ids: set[str] | frozenset[str] = frozenset(),
    ) -> int:
        """Compatibility name for availability-controller callers."""

        return self.refresh_evacuation_routes_for_topology_change(
            changed_facility_ids,
            force_all=True,
        )

    def _passenger_is_inside_station_for_alarm(
        self,
        passenger: PassengerAgent,
        *,
        completed_facility_id: str | None = None,
    ) -> bool:
        completed_facility = self.facilities_by_id.get(completed_facility_id)
        completed_stage = getattr(getattr(completed_facility, "spec", None), "stage", None)
        if completed_stage == FacilityStage.ENTRY_GATE.value:
            return True
        if completed_stage == FacilityStage.EXIT_GATE.value:
            return False
        completed_stages = {
            node.facility_stage
            for transition in passenger.goal_runtime.transitions
            if transition.event_kind == GoalEventKind.SERVICE_COMPLETED.value
            and (
                node := passenger.goal_runtime.graph.node(transition.before_node_id)
            ).facility_stage
            is not None
        }
        if FacilityStage.EXIT_GATE.value in completed_stages:
            return False
        if passenger.intent == AgentIntent.ENTER_AND_BOARD.value:
            return FacilityStage.ENTRY_GATE.value in completed_stages
        return True

    def _spawn_alighting_passengers_for_train(self, train: TrainAgent, count: int) -> None:
        if count <= 0:
            return

        doors = self.boarding_doors_for_train(train)
        if not doors:
            self.audit.record(
                "alighting_train_has_no_doors",
                source="demand_scheduler",
                severity="error",
                step=self.step_index,
                context={
                    "train_id": train.unique_id,
                    "platform_id": train.platform_id,
                    "due_persons": count,
                },
            )
            return

        door_spawn_counts: Counter[str] = Counter()
        for index in range(count):
            door = doors[(index + self.step_index + train.departed_trains) % len(doors)]
            local_index = door_spawn_counts[door.facility_id]
            door_spawn_counts[door.facility_id] += 1
            passenger = self._spawn_passenger(
                AgentIntent.EXIT_STATION,
                initial_position=self._alighting_spawn_position(door, local_index),
                initial_level_id=door.spec.exit_level_id or door.spec.entry_level_id,
            )
            passenger.assigned_platform_id = train.platform_id
            passenger.assigned_line_id = train.line_id
            passenger.assigned_direction = train.direction

    def _alighting_spawn_position(
        self,
        door: FacilityProcessAgent,
        local_index: int,
    ) -> tuple[float, float]:
        base_x, base_y = door.spec.exit_position
        anchor_x, anchor_y = door.spec.queue_anchor
        inward_x = anchor_x - base_x
        inward_y = anchor_y - base_y
        length = hypot(inward_x, inward_y)
        if length <= 0.001:
            inward_x, inward_y = 0.0, -1.0
        else:
            inward_x /= length
            inward_y /= length

        side_x = -inward_y
        side_y = inward_x
        spacing = max(0.35, self.scenario.jupedsim_agent_radius_units * 2.2)
        lane = local_index % 4
        row = local_index // 4
        side_offset = (lane - 1.5) * spacing
        inward_offset = 0.35 + row * max(
            0.25, self.scenario.jupedsim_agent_radius_units * 1.8
        )
        raw = (
            base_x + inward_x * inward_offset + side_x * side_offset,
            base_y + inward_y * inward_offset + side_y * side_offset,
        )
        level_id = door.spec.exit_level_id or door.spec.entry_level_id
        try:
            return project_to_safe_point(
                self.jupedsim_walkable_area(level_id),
                self.clamp_position(raw),
                clearance=max(0.02, self.scenario.jupedsim_agent_radius_units * 1.05),
                require_inside=False,
            )
        except Exception:
            return self.clamp_position(raw)

    @staticmethod
    def _split_count(count: int, buckets: int) -> list[int]:
        if buckets <= 0:
            return []
        base, remainder = divmod(max(0, count), buckets)
        return [base + (1 if index < remainder else 0) for index in range(buckets)]
