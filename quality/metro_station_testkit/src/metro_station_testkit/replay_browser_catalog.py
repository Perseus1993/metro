from __future__ import annotations

from itertools import product

from .layout_exploration_case import LayoutExplorationCase, validate_case_catalog


REPLAY_BROWSER_GENERATOR_VERSION = "replay_browser_trial.v1"
REPLAY_BROWSER_VIEWPORTS = (
    (1280, 720),
    (1600, 1000),
    (1920, 1080),
)
REPLAY_BROWSER_SCENES = (
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B06",
    "B07",
    "B08",
    "B09",
    "B10",
    "B11",
    "B12",
)


def replay_browser_cases() -> tuple[LayoutExplorationCase, ...]:
    cases = tuple(
        LayoutExplorationCase(
            suite_id="PM028-E5",
            case_id=f"E5-{scene_id}-{width}x{height}",
            generator_version=REPLAY_BROWSER_GENERATOR_VERSION,
            expected_class="AUDIT" if scene_id == "B10" else "VALID",
            factors={
                "scene_id": scene_id,
                "viewport_width": width,
                "viewport_height": height,
                "primary_evidence_viewport": width == 1600 and height == 1000,
            },
            seed=20261000 + int(scene_id[1:]),
            requirements=("PM-028", "PM-028-E5"),
            notes=(
                "Frontend damage-copy audit; contract-level rejection is tested separately."
                if scene_id == "B10"
                else ""
            ),
        )
        for scene_id, (width, height) in product(
            REPLAY_BROWSER_SCENES,
            REPLAY_BROWSER_VIEWPORTS,
        )
    )
    validate_case_catalog(cases)
    return cases

