from __future__ import annotations

from dataclasses import replace

from metro_alignment.metro_scene import build_metro_request
from metro_alignment.scenes import build_scene_config


def test_metro_request_preserves_physical_clock_backend_and_nondefault_seed() -> None:
    config = replace(
        build_scene_config("platform_boarding"),
        seed=99,
        jupedsim_desired_speed_mps=1.47,
    )
    request, design_sha256 = build_metro_request(config)
    assert request.seed == 99
    assert request.scenario.simulation_clock_mode == "physical"
    assert request.scenario.movement_backend_name == "jupedsim"
    assert request.scenario.movement_trace_sample_seconds == config.movement_trace_sample_seconds
    assert request.scenario.jupedsim_desired_speed_mps == 1.47
    assert len(design_sha256) == 64
