from __future__ import annotations

import unittest
from types import SimpleNamespace

from sandbox.metro_station_sandbox.agents.passenger import PassengerAgent
from sandbox.metro_station_sandbox.design.templates import create_design
from sandbox.metro_station_sandbox.planning.plan import AgentIntent
from sandbox.metro_station_sandbox.runtime.mesa_model import MetroStationModel
from sandbox.metro_station_sandbox.runtime.simulation_clock import (
    LEGACY_SCALED_CLOCK,
    PHYSICAL_CLOCK,
    SimulationClock,
)
from sandbox.metro_station_sandbox.station.scenario import StationSandboxScenario


class SimulationClockTests(unittest.TestCase):
    def test_physical_clock_couples_five_seconds_but_rejects_coarse_process_evidence(self) -> None:
        clock = SimulationClock(
            mesa_tick_seconds=5.0,
            jupedsim_dt_seconds=0.01,
            mode=PHYSICAL_CLOCK,
            legacy_iterations_per_tick=150,
        )

        self.assertEqual(500, clock.jupedsim_iterations_per_tick)
        self.assertAlmostEqual(5.0, clock.jupedsim_elapsed_seconds_per_tick)
        self.assertFalse(clock.research_valid)
        self.assertEqual(
            "process_time_resolution_exceeds_one_second",
            clock.as_dict()["research_invalid_reason"],
        )

    def test_one_second_physical_clock_is_research_valid(self) -> None:
        clock = SimulationClock(
            mesa_tick_seconds=1.0,
            jupedsim_dt_seconds=0.01,
            mode=PHYSICAL_CLOCK,
        )

        self.assertTrue(clock.research_valid)
        self.assertNotIn("research_invalid_reason", clock.as_dict())

    def test_legacy_clock_preserves_existing_iteration_count_and_marks_output(self) -> None:
        clock = SimulationClock(
            mesa_tick_seconds=5.0,
            jupedsim_dt_seconds=0.01,
            mode=LEGACY_SCALED_CLOCK,
            legacy_iterations_per_tick=150,
        )

        self.assertEqual(150, clock.jupedsim_iterations_per_tick)
        self.assertAlmostEqual(1.5, clock.jupedsim_elapsed_seconds_per_tick)
        self.assertFalse(clock.research_valid)
        self.assertEqual("legacy_time_scaling", clock.as_dict()["research_invalid_reason"])

    def test_physical_clock_rejects_non_integral_time_ratio(self) -> None:
        with self.assertRaisesRegex(ValueError, "integer multiple"):
            SimulationClock(
                mesa_tick_seconds=1.0,
                jupedsim_dt_seconds=0.03,
                mode=PHYSICAL_CLOCK,
            )

    def test_clock_can_be_built_from_legacy_scenario_shape(self) -> None:
        clock = SimulationClock.from_scenario(
            SimpleNamespace(tick_seconds=5, jupedsim_iterations_per_tick=150)
        )

        self.assertEqual(LEGACY_SCALED_CLOCK, clock.mode)
        self.assertEqual(150, clock.jupedsim_iterations_per_tick)

    def test_physical_model_advances_jupedsim_by_one_mesa_tick(self) -> None:
        scenario = StationSandboxScenario(
            station_name="clock_test",
            hour=18,
            minutes=1,
            tick_seconds=1,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            source_label="unit_test",
            sample_hours=1,
            station_design=create_design("single_level_terminal"),
            goal_graph_mode="active",
            simulation_clock_mode=PHYSICAL_CLOCK,
            jupedsim_dt_seconds=0.01,
            audit_enabled=False,
            audit_print_events=False,
        )
        model = MetroStationModel(scenario, seed=91)
        if not model.jupedsim.status.available:
            self.skipTest(model.jupedsim.status.message)
        passenger = PassengerAgent(
            model,
            group_size=1,
            created_step=0,
            intent=AgentIntent.ENTER_AND_BOARD,
        )

        results = model.movement_backend.step_all([passenger])

        self.assertEqual(1, len(results))
        sessions = list(model.movement_backend._sessions.values())
        self.assertEqual(1, len(sessions))
        simulation = sessions[0]._simulation
        self.assertEqual(100, simulation.iteration_count())
        self.assertAlmostEqual(1.0, simulation.elapsed_time())


if __name__ == "__main__":
    unittest.main()
