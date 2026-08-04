from __future__ import annotations

import unittest
from dataclasses import replace
from math import hypot

from sandbox.metro_station_sandbox.design.templates import create_design
from sandbox.metro_station_sandbox.planning.behavior import region_goal_for_passenger
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from sandbox.metro_station_sandbox.runtime.demand_scheduler import DemandScheduler
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from metro_station_experiments.report import _peak_queue_metrics
from metro_station_experiments.evacuation_metrics import evacuation_metrics
from sandbox.metro_station_sandbox.station.evacuation import (
    EVACUATION_MODE,
    EvacuationScenarioConfig,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario
from metro_station_visualizer.mesa_export import mesa_frames_to_visual_tracks


def scenario_for_evacuation(
    *,
    initial_persons: int = 2,
    group_size: int = 1,
    alarm_delay_seconds: float = 0.0,
    minutes: int = 2,
    tick_seconds: int = 1,
) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name="evacuation_test",
        hour=18,
        minutes=minutes,
        tick_seconds=tick_seconds,
        group_size=group_size,
        entry_count_hour=9000,
        exit_count_hour=9000,
        transfer_count_hour=9000,
        source_label="unit_test",
        sample_hours=1,
        scenario_mode=EVACUATION_MODE,
        evacuation=EvacuationScenarioConfig(
            initial_platform_persons=initial_persons,
            alarm_delay_seconds=alarm_delay_seconds,
        ),
        station_design=create_design("single_level_terminal"),
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


class EvacuationScenarioTests(unittest.TestCase):
    def test_active_goal_graph_completes_every_evacuation_passenger(self) -> None:
        scenario = replace(
            scenario_for_evacuation(initial_persons=10, minutes=3),
            goal_graph_mode="active",
        )
        model = MetroStationModel(scenario, seed=94)
        model.run()

        self.assertEqual(10, model.evacuated_persons)
        self.assertEqual(10, len(model.passenger_goal_runtimes))
        self.assertTrue(
            all(
                runtime.state.current_node_id == "complete"
                for runtime in model.passenger_goal_runtimes.values()
            )
        )

    def test_evacuation_mode_requires_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "evacuation config is required"):
            StationSandboxScenario(
                station_name="broken",
                hour=18,
                minutes=1,
                tick_seconds=1,
                group_size=1,
                entry_count_hour=0,
                exit_count_hour=0,
                source_label="unit_test",
                sample_hours=1,
                scenario_mode=EVACUATION_MODE,
                station_design=create_design("single_level_terminal"),
                goal_graph_mode="active",
            )

    def test_initial_population_must_be_exact_for_group_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "divisible by group_size"):
            scenario_for_evacuation(initial_persons=3, group_size=2)

    def test_scheduler_ignores_normal_demand_and_spawns_initial_population_once(self) -> None:
        scenario = scenario_for_evacuation(initial_persons=4, group_size=2)
        scheduler = DemandScheduler.from_scenario(scenario, rng=None)

        self.assertEqual(
            2,
            scheduler.due_by_intent(0)[AgentIntent.EVACUATE_STATION.value],
        )
        self.assertEqual({}, dict(scheduler.due_by_intent(1)))
        self.assertEqual({}, scheduler.alighting_schedule)
        self.assertEqual(1, scenario.demand_steps)

    def test_alarm_delay_moves_single_initial_spawn_step(self) -> None:
        scenario = scenario_for_evacuation(
            initial_persons=1,
            alarm_delay_seconds=5.0,
            tick_seconds=1,
        )
        scheduler = DemandScheduler.from_scenario(scenario, rng=None)

        self.assertEqual({}, dict(scheduler.due_by_intent(0)))
        self.assertEqual(
            1,
            scheduler.due_by_intent(5)[AgentIntent.EVACUATE_STATION.value],
        )
        self.assertEqual(6, scenario.demand_steps)

    def test_spawned_evacuation_passenger_has_distinct_intent_and_region_goal(self) -> None:
        model = MetroStationModel(scenario_for_evacuation(initial_persons=1), seed=92)

        model.spawn_passengers()

        self.assertEqual(1, len(model.passengers))
        passenger = model.passengers[0]
        self.assertEqual(AgentIntent.EVACUATE_STATION.value, passenger.intent)
        self.assertEqual(AgentIntent.EVACUATE_STATION.value, passenger.plan.intent)
        goal = region_goal_for_passenger(passenger)
        self.assertEqual("station_exterior_safe_zone", goal.destination_region)
        self.assertEqual(1, model.spawned_persons)
        self.assertEqual(0, model.spawned_persons_by_intent[AgentIntent.ENTER_AND_BOARD.value])

    def test_dense_initial_population_has_native_body_clearance_before_first_step(self) -> None:
        scenario = replace(
            scenario_for_evacuation(initial_persons=50),
            station_design=create_design("three_level_transfer"),
        )
        model = MetroStationModel(scenario, seed=42)

        model.spawn_passengers()

        minimum = scenario.jupedsim_agent_radius_units * 2.2
        admitted = len(model.passengers)
        pending = sum(model.pending_spawn_groups.values())
        self.assertGreater(admitted, 0)
        self.assertEqual(50, admitted + pending)
        self.assertEqual(50, model.spawned_persons + pending)
        self.assertGreater(pending, 0)
        self.assertGreaterEqual(
            model.spatial_capacity_event_counts["capacity.admission_exhausted"],
            1,
        )
        self.assertTrue(
            all(
                hypot(
                    left.pos[0] - right.pos[0],
                    left.pos[1] - right.pos[1],
                )
                >= minimum - 1e-9
                for index, left in enumerate(model.passengers)
                for right in model.passengers[index + 1 :]
                if left.current_level_id == right.current_level_id
            )
        )

    def test_evacuation_completion_records_safe_zone_terminal_event(self) -> None:
        scenario = scenario_for_evacuation(initial_persons=1)
        model = MetroStationModel(scenario, seed=93)

        frames = model.run()

        self.assertEqual(0, len(model.passengers))
        self.assertEqual(1, model.departed_persons)
        self.assertEqual(1, model.evacuated_persons)
        self.assertEqual(1, len(model.passenger_terminal_events))
        event = model.passenger_terminal_events[0]
        self.assertEqual("reached_safe_zone", event.event)
        self.assertEqual(AgentIntent.EVACUATE_STATION.value, event.intent)
        self.assertGreater(event.time_seconds, 0.0)
        self.assertEqual(1, frames[-1]["metrics"]["evacuated_persons"])

        payload = mesa_frames_to_visual_tracks(
            frames=frames,
            scenario=scenario,
            facilities=model.facilities,
            service_events=model.facility_service_events,
            terminal_events=model.passenger_terminal_events,
        )
        self.assertEqual(1, payload["clearance_audit"]["evacuated_persons"])
        self.assertEqual(event.time_seconds, payload["clearance_audit"]["clearance_time_s"])
        self.assertEqual("reached_safe_zone", payload["terminal_events"][0]["event"])
        self.assertFalse(payload["scenario"]["research_readiness"]["ready_for_real_world_claims"])
        self.assertIn(
            "model_not_independently_validated",
            payload["scenario"]["research_readiness"]["blockers"],
        )

    def test_peak_queue_metrics_use_all_frames_instead_of_final_frame(self) -> None:
        peaks = _peak_queue_metrics(
            [
                {"metrics": {"gate_queue_persons": 2, "vertical_queue_persons": 1}},
                {"metrics": {"gate_queue_persons": 9, "vertical_queue_persons": 7}},
                {"metrics": {"gate_queue_persons": 0, "vertical_queue_persons": 0}},
            ]
        )

        self.assertEqual(9, peaks["max_gate_queue_persons"])
        self.assertEqual(7, peaks["max_vertical_queue_persons"])

    def test_evacuation_percentiles_require_population_thresholds(self) -> None:
        metrics = evacuation_metrics(
            [
                {
                    "event": "reached_safe_zone",
                    "time_seconds": 10.0,
                    "duration_seconds": 10.0,
                    "persons": 9,
                },
                {
                    "event": "reached_safe_zone",
                    "time_seconds": 20.0,
                    "duration_seconds": 20.0,
                    "persons": 1,
                },
            ],
            total_persons=10,
            remaining_persons=0,
        )

        self.assertEqual(10.0, metrics["t90_seconds"])
        self.assertEqual(20.0, metrics["t95_seconds"])
        self.assertEqual(20.0, metrics["t99_seconds"])
        self.assertEqual(20.0, metrics["clearance_time_seconds"])
        self.assertEqual(11.0, metrics["mean_evacuation_duration_seconds"])

    def test_incomplete_evacuation_has_no_clearance_or_unreached_percentile(self) -> None:
        metrics = evacuation_metrics(
            [
                {
                    "event": "reached_safe_zone",
                    "time_seconds": 10.0,
                    "duration_seconds": 10.0,
                    "persons": 8,
                }
            ],
            total_persons=10,
            remaining_persons=2,
        )

        self.assertIsNone(metrics["clearance_time_seconds"])
        self.assertIsNone(metrics["t90_seconds"])
        self.assertEqual(0.8, metrics["completion_rate"])


if __name__ == "__main__":
    unittest.main()
