from __future__ import annotations

from sandbox.metro_station_sandbox.design.schema import StationDesignDocument
from metro_station_acceptance.preset_acceptance import (
    run_preset_acceptance_case,
)
from scripts.run_station_preset_acceptance import (
    _compile_layout,
    _frontend_preset_layouts,
)


def test_all_guided_presets_clear_with_topological_trajectory_samples() -> None:
    operations = {
        "minutes": 12,
        "group_size": 1,
        "entry_count_hour": 180,
        "exit_count_hour": 180,
        "transfer_count_hour": 180,
    }
    layouts = _frontend_preset_layouts(operations)

    results = []
    for layout in layouts:
        compiled = _compile_layout(layout, operations)
        result, _ = run_preset_acceptance_case(
            preset_id=layout["preset"]["id"],
            document=StationDesignDocument.from_dict(compiled["document"]),
            operations=compiled["operations"],
            seed=41,
            sample_count=3,
        )
        results.append(result)

    failures = {
        result["preset_id"]: [
            check for check, passed in result["checks"].items() if not passed
        ]
        for result in results
        if result["status"] != "ok"
    }
    assert not failures
    assert len(results) == 5
    assert all(result["clearance"]["cleared"] for result in results)
    assert all(
        sample["status"] == "ok"
        for result in results
        for sample in result["sampled_trajectories"]
    )
