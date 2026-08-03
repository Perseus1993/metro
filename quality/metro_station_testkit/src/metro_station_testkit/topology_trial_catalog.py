from __future__ import annotations

from itertools import product

from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


TOPOLOGY_TRIAL_GENERATOR_VERSION = "topology_trial_generator.v1"
FOOTPRINT_SHAPES = ("RECT", "L", "T", "NECK")
VERTICAL_MODES = ("FULL", "CHAIN", "DUAL_CLUSTER")
FARE_MODES = ("BIDIRECTIONAL", "SPLIT_ENTRY_EXIT")


def topology_core_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = tuple(
        LayoutExplorationCase(
            suite_id="PM028-E1",
            case_id=f"E1-CORE-{footprint}-{vertical}-{fare}-M{int(mirror)}",
            generator_version=TOPOLOGY_TRIAL_GENERATOR_VERSION,
            expected_class="VALID",
            factors={
                "footprint": footprint,
                "vertical": vertical,
                "fare": fare,
                "mirror": mirror,
                "level_count": 3,
            },
            seed=20260718 + index,
        )
        for index, (footprint, vertical, fare, mirror) in enumerate(
            product(FOOTPRINT_SHAPES, VERTICAL_MODES, FARE_MODES, (False, True))
        )
    )
    validate_case_catalog(cases)
    return cases

