from __future__ import annotations

from itertools import product

from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


SCALE_SOAK_GENERATOR_VERSION = "scale_soak_trial.v1"
SCALE_SOAK_WORKLOADS = (
    "HEAVY-SIX-ELEVATOR",
    "BOTTLENECK-HALL",
    "DUAL-CONNECTOR-CLUSTER",
    "DEMAND-FAULT-COUPLING",
)


def scale_soak_cases(repetitions: int = 2) -> tuple[LayoutExplorationCase, ...]:
    if repetitions < 2:
        raise ValueError("scale soak requires at least baseline and comparison repetitions")
    cases = tuple(
        LayoutExplorationCase(
            suite_id="PM028-E6-SOAK",
            case_id=f"E6-SOAK-{workload}-R{repetition + 1:02d}",
            generator_version=SCALE_SOAK_GENERATOR_VERSION,
            expected_class="STRESS",
            factors={"workload": workload, "repetition": repetition + 1},
            seed=42,
            requirements=("PM-028", "PM-028-E6"),
        )
        for workload, repetition in product(SCALE_SOAK_WORKLOADS, range(repetitions))
    )
    validate_case_catalog(cases)
    return cases

