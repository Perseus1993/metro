from __future__ import annotations

import pytest

from metro_alignment.formal_profiles import (
    MULTI_SEED_NIGHTLY_SEEDS,
    final_ladder_profile,
    multi_seed_nightly_profile,
)


def test_final_profile_freezes_ladder_and_qualifier_order() -> None:
    profile = final_ladder_profile()
    assert tuple(control.control_id for control in profile.controls) == (
        "exit-only-350",
        "entry-only-600",
        "entry-tail-saturated-flow",
        "mixed-600",
    )
    assert profile.controls[0].horizon_steps == 350
    assert profile.controls[1].horizon_steps == 600
    assert profile.controls[2].saturated_flow is not None
    assert profile.publication_control_id == "mixed-600"


def test_nightly_profile_accepts_only_preregistered_seeds() -> None:
    for seed in MULTI_SEED_NIGHTLY_SEEDS:
        assert multi_seed_nightly_profile(seed).controls[0].seed == seed
    with pytest.raises(ValueError, match="nightly seed"):
        multi_seed_nightly_profile(40)
