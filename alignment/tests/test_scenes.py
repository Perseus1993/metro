from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from metro_alignment.scenes import SCENE_FACTORIES, build_scene_config, list_scene_configs
from metro_alignment.scenes.corridor_unidirectional import (
    CorridorUnidirectionalConfig,
)
from metro_alignment.scenes.corridor_unidirectional import (
    build_scene_config as build_corridor,
)
from metro_alignment.scenes.designs import build_station_design
from metro_alignment.scenes.platform_boarding import build_scene_config as build_platform


def _design_hash(config) -> str:
    payload = json.dumps(build_station_design(config).as_dict(), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def test_scene_registry_and_builder_have_one_default() -> None:
    assert build_corridor() == CorridorUnidirectionalConfig()
    assert build_scene_config("corridor_unidirectional").status == "pending"
    with pytest.raises(ValueError, match="dimensions"):
        build_corridor(width_m=0.0)


def test_pending_scene_cannot_masquerade_as_runnable() -> None:
    with pytest.raises(RuntimeError, match="pending"):
        build_station_design(build_scene_config("bottleneck"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "future"),
        ("minutes", True),
        ("seed", 1.5),
        ("alighting_source_lateral_offset_m", -0.1),
    ],
)
def test_scene_contract_rejects_runtime_type_and_enum_errors(field, value) -> None:
    with pytest.raises(ValueError):
        replace(build_scene_config("platform_boarding"), **{field: value})


@pytest.mark.parametrize(
    "scene_id",
    ["../escape", "C:relative", "NUL", "scene/name", " scene "],
)
def test_scene_id_must_be_a_portable_slug(scene_id: str) -> None:
    with pytest.raises(ValueError, match="portable slug"):
        replace(build_scene_config("platform_boarding"), scene_id=scene_id)


def test_scene_registry_key_must_match_scene_id(monkeypatch) -> None:
    current = build_scene_config("platform_boarding")
    monkeypatch.setitem(SCENE_FACTORIES, "wrong_key", lambda: current)
    with pytest.raises(ValueError, match="must equal scene_id"):
        list_scene_configs()


def test_platform_dimensions_change_compiled_design() -> None:
    default = build_platform()
    assert default.alighting_source_lateral_offset_m == pytest.approx(10.0)
    assert default.scene_class == "synthetic_declared"
    assert default.geometry_evidence_status == "proxy"
    assert "internal obstacles" in default.geometry_evidence
    wider = build_platform(platform_length_m=90.0, platform_width_m=18.0)
    assert _design_hash(default) != _design_hash(wider)
    design = build_station_design(wider)
    hall = design.element_by_id()["main_hall"].geometry
    assert hall.width_m == pytest.approx(90.0)
    assert hall.height_m == pytest.approx(18.0)
    assert wider.measurement_bounds_m == (4.0, 10.0, 94.0, 28.0)
    with pytest.raises(ValueError, match="requires a lowercase SHA-256"):
        replace(default, geometry_evidence_status="observed_matched")
    with pytest.raises(ValueError, match="must be proxy or observed_matched"):
        replace(default, geometry_evidence_status="trusted")
    with pytest.raises(ValueError, match="scene_class"):
        replace(default, scene_class="unverified")
