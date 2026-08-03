from __future__ import annotations

from itertools import product

from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


METAMORPHIC_GENERATOR_VERSION = "metamorphic_trial.v1"
TRANSFORMS = ("M1-REORDER", "M2-MIRROR", "M3-REMOVE-DECOR", "M4-ADD-ELEVATOR", "M5-TRANSLATE")
INJECTIONS = (
    "I1-DELETE-EDGE",
    "I2-WRONG-RUNTIME-BINDING",
    "I3-DELETE-ASSET-BINDING",
    "I4-WRONG-QUEUE-OWNER",
    "I5-PARTIAL-MIRROR",
)
SENSITIVITY_BASE_INDICES = (5, 6, 7, 9, 10, 11, 13, 14, 15, 17)


def metamorphic_pair_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = tuple(
        LayoutExplorationCase(
            suite_id="PM028-E4",
            case_id=f"E4-B{base_index:02d}-{transform}",
            generator_version=METAMORPHIC_GENERATOR_VERSION,
            expected_class="VALID",
            factors={"base_index": base_index, "transform": transform},
            seed=20260800 + base_index,
        )
        for base_index, transform in product(range(20), TRANSFORMS)
    )
    validate_case_catalog(cases)
    return cases


def metamorphic_sensitivity_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = tuple(
        LayoutExplorationCase(
            suite_id="PM028-E4-SENSITIVITY",
            case_id=f"E4-SENS-B{base_index:02d}-{injection}",
            generator_version=METAMORPHIC_GENERATOR_VERSION,
            expected_class="INVALID",
            factors={"base_index": base_index, "injection": injection},
            seed=20260900 + base_index,
            expected_failure_stage={
                "I1-DELETE-EDGE": "topology",
                "I2-WRONG-RUNTIME-BINDING": "replay",
                "I3-DELETE-ASSET-BINDING": "asset",
                "I4-WRONG-QUEUE-OWNER": "design",
                "I5-PARTIAL-MIRROR": "geometry",
            }[injection],
            expected_diagnostic_codes=(f"sensitivity.{injection.lower()}",),
        )
        for base_index, injection in product(SENSITIVITY_BASE_INDICES, INJECTIONS)
    )
    validate_case_catalog(cases)
    return cases
