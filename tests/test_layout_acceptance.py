from __future__ import annotations

import unittest

from sandbox.metro_station_sandbox.movement.backend import MovementBackend, MovementResult
from metro_station_acceptance.goal_journey_acceptance import (
    run_four_journey_acceptance,
)
from metro_station_acceptance.layout_acceptance import (
    acceptance_tier_profile,
    run_cross_layout_acceptance,
)
from metro_station_acceptance.layout_acceptance_contract import (
    LAYOUT_IDS,
    inspect_layout_contract,
)
from metro_station_acceptance.layout_acceptance_report import (
    render_layout_acceptance_markdown,
)
from metro_station_acceptance.layout_acceptance_merge import (
    merge_layout_acceptance_payloads,
)
from metro_station_acceptance.operational_acceptance_scenarios import (
    FACILITY_CLOSURE_RECOVERY,
    SINGLE_FACILITY,
    TRAIN_OUTAGE_RECOVERY,
    operational_scenario,
)
from sandbox.metro_station_sandbox.station.compiler import DesignCompiler


class InstantMovementBackend(MovementBackend):
    def move(self, passenger) -> MovementResult:
        return MovementResult(passenger.unique_id, passenger.target, reached=True)


class LayoutAcceptanceTests(unittest.TestCase):
    def test_every_layout_satisfies_the_same_topology_contract(self) -> None:
        check_names: set[tuple[str, ...]] = set()
        for layout_id in LAYOUT_IDS:
            with self.subTest(layout_id=layout_id):
                report = inspect_layout_contract(layout_id)
                self.assertEqual("ok", report.status, report.as_dict())
                check_names.add(tuple(report.checks))
                self.assertGreater(report.facility_counts["entry_gate"], 0)
                self.assertGreater(report.facility_counts["exit_gate"], 0)
                self.assertGreater(report.facility_counts["boarding_door"], 0)
        self.assertEqual(1, len(check_names))

    def test_four_journeys_complete_on_every_layout(self) -> None:
        for layout_id in LAYOUT_IDS:
            with self.subTest(layout_id=layout_id):
                report = run_four_journey_acceptance(
                    layout_id=layout_id,
                    seeds=(42,),
                    movement_backend_factory=InstantMovementBackend,
                    normal_options={
                        "entry_count_hour": 120,
                        "exit_count_hour": 120,
                        "transfer_count_hour": 120,
                        "demand_minutes": 2,
                        "clearance_minutes": 25,
                    },
                    evacuation_persons=12,
                    evacuation_minutes=8,
                )
                self.assertEqual("ok", report.status, report.as_dict())
                self.assertEqual(layout_id, report.layout_id)

    def test_operational_targets_are_resolved_from_each_compiled_layout(self) -> None:
        for layout_id in LAYOUT_IDS:
            for scenario_id in (
                SINGLE_FACILITY,
                FACILITY_CLOSURE_RECOVERY,
                TRAIN_OUTAGE_RECOVERY,
            ):
                with self.subTest(layout_id=layout_id, scenario_id=scenario_id):
                    scenario = operational_scenario(scenario_id, layout_id=layout_id)
                    layout = DesignCompiler.compile(scenario.station_design, scenario)
                    facility_ids = {spec.facility_id for spec in layout.facilities}
                    platform_ids = {item[0] for item in layout.platform_descriptors()}
                    self.assertLessEqual(set(scenario.disabled_facility_ids), facility_ids)
                    self.assertLessEqual(
                        {event.facility_id for event in scenario.facility_availability_events},
                        facility_ids,
                    )
                    self.assertLessEqual(
                        {event.platform_id for event in scenario.train_service_events},
                        platform_ids,
                    )

    def test_harness_builds_complete_matrix_and_markdown_evidence(self) -> None:
        report = run_cross_layout_acceptance(
            tier="smoke",
            layout_ids=("two_level_island_platform",),
            seeds=(42,),
            movement_backend_factory=InstantMovementBackend,
        )
        layout = report.layouts[0]
        self.assertTrue(report.checks["journey_matrix_complete"])
        self.assertTrue(report.checks["operational_matrix_complete"])
        self.assertTrue(layout.checks["deterministic_replay"])
        self.assertEqual(5, len(layout.operations.reports))
        markdown = render_layout_acceptance_markdown(report)
        self.assertIn("two_level_island_platform", markdown)
        self.assertIn("Determinism", markdown)
        merged = merge_layout_acceptance_payloads(
            (report.as_dict(),),
            required_layout_ids=("two_level_island_platform",),
        )
        self.assertTrue(merged["checks"]["all_requested_layouts_reported"])
        self.assertTrue(merged["checks"]["journey_matrix_complete"])

    def test_acceptance_tiers_freeze_release_seed_and_load_contract(self) -> None:
        release = acceptance_tier_profile("release")
        self.assertEqual((41, 42, 43), release.seeds)
        self.assertEqual(1800, release.normal_options["entry_count_hour"])
        self.assertEqual(30, release.evacuation_persons)


if __name__ == "__main__":
    unittest.main()
