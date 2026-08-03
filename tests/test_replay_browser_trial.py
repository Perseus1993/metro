from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from metro_station.application.replay import AssetManifest, ReplayPackage, StationScene
from metro_station_acceptance.replay_browser_acceptance import (
    run_replay_browser_acceptance,
)
from metro_station_testkit.replay_browser_catalog import (
    REPLAY_BROWSER_SCENES,
    REPLAY_BROWSER_VIEWPORTS,
    replay_browser_cases,
)
from metro_station_testkit.replay_browser_scenes import build_replay_browser_scene


def test_replay_browser_catalog_has_12_by_3_exact_matrix() -> None:
    cases = replay_browser_cases()

    assert len(cases) == 36
    assert {str(case.factors["scene_id"]) for case in cases} == set(
        REPLAY_BROWSER_SCENES
    )
    assert {
        (
            int(case.factors["viewport_width"]),
            int(case.factors["viewport_height"]),
        )
        for case in cases
    } == set(REPLAY_BROWSER_VIEWPORTS)
    assert sum(bool(case.factors["primary_evidence_viewport"]) for case in cases) == 12


def test_replay_browser_scenes_cover_elevators_geometry_damage_and_placement() -> None:
    scenes = {
        scene_id: build_replay_browser_scene(scene_id)
        for scene_id in REPLAY_BROWSER_SCENES
    }

    assert [scenes[item].expected_elevator_count for item in ("B01", "B02", "B03", "B04")] == [
        0,
        1,
        3,
        6,
    ]
    assert scenes["B08"].expected_level_count == 3
    assert set(scenes["B10"].expected_diagnostic_codes) == {
        "asset_binding_missing",
        "asset_binding_unresolved",
    }
    b11_shapes = {
        str(item["geometry"]["shape"])
        for item in scenes["B11"].station_scene["entities"]
    }
    assert {"polygon", "polyline", "point"}.issubset(b11_shapes)
    assert scenes["B12"].rotated_entity_id is not None
    placement = next(
        item["placement"]
        for item in scenes["B12"].asset_manifest["bindings"]
        if item["scene_entity_id"] == scenes["B12"].placement_entity_id
    )
    assert placement["scale"] == [1.2, 0.8]
    assert placement["rotation_deg"] == 15.0
    assert placement["offset_m"] == [1.0, -0.5]


def test_asset_and_replay_contracts_reject_unknown_references() -> None:
    source = build_replay_browser_scene("B02")
    unknown_asset = deepcopy(source.asset_manifest)
    unknown_asset.pop("semantic_fingerprint", None)
    unknown_asset["bindings"][0]["asset_id"] = "unknown:asset:v1"
    with pytest.raises(ValueError, match="unknown asset"):
        AssetManifest.from_dict(unknown_asset)

    scene_payload = deepcopy(source.station_scene)
    scene_payload.pop("semantic_fingerprint", None)
    station_scene = StationScene.from_dict(scene_payload)
    valid_manifest = AssetManifest.from_dict(source.asset_manifest)
    unknown_entity_manifest = AssetManifest(
        assets=valid_manifest.assets,
        bindings=(
            *valid_manifest.bindings[:-1],
            type(valid_manifest.bindings[-1])(
                binding_id=valid_manifest.bindings[-1].binding_id,
                scene_entity_id="element:unknown",
                asset_id=valid_manifest.bindings[-1].asset_id,
                placement=valid_manifest.bindings[-1].placement,
            ),
        ),
    )
    with pytest.raises(ValueError, match="unknown scene entity"):
        ReplayPackage(
            source_run_id="unknown-entity",
            station_scene=station_scene,
            asset_manifest=unknown_entity_manifest,
        )


def test_all_36_replay_browser_runs_pass_and_emit_12_primary_screenshots(
    tmp_path: Path,
) -> None:
    report = run_replay_browser_acceptance(tmp_path)

    assert report.status == "ok", report.failed_case_ids
    assert len(report.results) == 36
    assert len(tuple((tmp_path / "screenshots").glob("*.png"))) == 12

