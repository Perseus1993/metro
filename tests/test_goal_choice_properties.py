from __future__ import annotations

import itertools
import random
import unittest

from sandbox.metro_station_sandbox.planning.goal_choice import (
    MinimumPerceivedCostSelector,
)
from sandbox.metro_station_sandbox.planning.goal_events import (
    DecisionObservation,
    FacilityObservation,
)


def candidate(
    facility_id: str,
    *,
    stage: str = "entry_gate",
    available: bool = True,
    reachable: bool = True,
    walking: float = 1.0,
    waiting: float = 1.0,
    density: float = 0.0,
) -> FacilityObservation:
    return FacilityObservation(
        facility_id=facility_id,
        stage=stage,
        available=available,
        reachable=reachable,
        walking_time_seconds=walking,
        queue_persons=0,
        estimated_wait_seconds=waiting,
        local_density_persons_m2=density,
    )


class GoalChoicePropertyTests(unittest.TestCase):
    def choose(self, candidates, selector=None):
        observation = DecisionObservation(
            time_seconds=1.0,
            current_region_id="decision",
            candidates=tuple(candidates),
        )
        return (selector or MinimumPerceivedCostSelector()).choose(
            "entry_gate",
            observation,
        )

    def test_selection_is_invariant_to_candidate_order(self) -> None:
        candidates = (
            candidate("gate_1", walking=2, waiting=8),
            candidate("gate_2", walking=4, waiting=2),
            candidate("gate_3", walking=3, waiting=6),
            candidate("gate_4", walking=1, waiting=9),
        )
        selected_ids = {
            self.choose(permutation).facility_id
            for permutation in itertools.permutations(candidates)
        }
        self.assertEqual({"gate_2"}, selected_ids)

    def test_unavailable_unreachable_and_wrong_stage_are_filtered(self) -> None:
        result = self.choose(
            (
                candidate("closed", available=False, walking=0, waiting=0),
                candidate("blocked", reachable=False, walking=0, waiting=0),
                candidate("wrong_stage", stage="exit_gate", walking=0, waiting=0),
                candidate("eligible", walking=5, waiting=5),
            )
        )
        self.assertEqual("eligible", result.facility_id)

    def test_empty_or_fully_filtered_candidates_return_none(self) -> None:
        self.assertIsNone(self.choose(()))
        self.assertIsNone(self.choose((candidate("closed", available=False),)))

    def test_density_and_custom_weights_change_choice_predictably(self) -> None:
        candidates = (
            candidate("dense_near", walking=1, waiting=1, density=4),
            candidate("clear_far", walking=8, waiting=2, density=0),
        )
        self.assertEqual("clear_far", self.choose(candidates).facility_id)

        ignore_density = MinimumPerceivedCostSelector(density_weight=0)
        self.assertEqual("dense_near", self.choose(candidates, ignore_density).facility_id)

    def test_ties_are_deterministic_by_facility_id(self) -> None:
        candidates = (
            candidate("gate_b", walking=2, waiting=3),
            candidate("gate_a", walking=1, waiting=4),
        )
        self.assertEqual("gate_a", self.choose(candidates).facility_id)

    def test_random_candidate_pools_match_reference_cost(self) -> None:
        rng = random.Random(20260712)
        selector = MinimumPerceivedCostSelector()
        for case_index in range(250):
            pool = tuple(
                candidate(
                    f"gate_{index:02d}",
                    available=rng.random() > 0.15,
                    reachable=rng.random() > 0.1,
                    walking=rng.random() * 30,
                    waiting=rng.random() * 60,
                    density=rng.random() * 5,
                )
                for index in range(rng.randint(1, 20))
            )
            eligible = [item for item in pool if item.available and item.reachable]
            expected = (
                min(
                    eligible,
                    key=lambda item: (
                        item.walking_time_seconds
                        + item.estimated_wait_seconds
                        + 4 * item.local_density_persons_m2,
                        item.facility_id,
                    ),
                ).facility_id
                if eligible
                else None
            )
            result = self.choose(pool, selector)
            with self.subTest(case=case_index):
                self.assertEqual(expected, None if result is None else result.facility_id)


if __name__ == "__main__":
    unittest.main()
