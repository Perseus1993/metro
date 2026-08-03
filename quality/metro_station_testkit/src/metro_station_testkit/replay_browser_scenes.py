from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from metro_station.adapters.simulation.design.schema import DesignElement, ElementGeometry
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station.application.replay import AssetManifest

from .layout_exploration_case import LayoutExplorationCase
from .layout_recipe import LayoutRecipe
from .layout_scenario_generator import generate_layout
from .topology_trial_designs import generate_topology_trial_design


@dataclass(frozen=True)
class ReplayBrowserScene:
    scene_id: str
    station_scene: dict[str, Any]
    asset_manifest: dict[str, Any]
    expected_diagnostic_codes: tuple[str, ...]
    expected_elevator_count: int
    expected_level_count: int
    rotated_entity_id: str | None = None
    placement_entity_id: str | None = None


def build_replay_browser_scene(scene_id: str) -> ReplayBrowserScene:
    document = _design(scene_id)
    scenario = _scenario(scene_id, document)
    layout = DesignCompiler.compile(document, scenario)
    scene = compile_station_scene(scenario, layout.facilities)
    manifest = compile_procedural_asset_manifest(scene)
    scene_payload = scene.as_dict()
    manifest_payload = manifest.as_dict()
    expected_diagnostics: tuple[str, ...] = ()
    rotated_entity_id = None
    placement_entity_id = None

    if scene_id == "B10":
        manifest_payload, expected_diagnostics = _damaged_frontend_manifest(manifest_payload)
    elif scene_id == "B12":
        rotated_entity_id = _rotated_entity_id(scene_payload)
        placement_entity_id = rotated_entity_id
        manifest_payload = _placement_override(manifest, rotated_entity_id).as_dict()

    elevator_count = sum(
        entity.get("kind") == "elevator" for entity in scene_payload["entities"]
    )
    return ReplayBrowserScene(
        scene_id=scene_id,
        station_scene=scene_payload,
        asset_manifest=manifest_payload,
        expected_diagnostic_codes=expected_diagnostics,
        expected_elevator_count=elevator_count,
        expected_level_count=len(scene_payload["levels"]),
        rotated_entity_id=rotated_entity_id,
        placement_entity_id=placement_entity_id,
    )


def _design(scene_id: str):
    if scene_id in {"B05", "B06", "B07", "B08", "B09"}:
        factors = {
            "B05": ("L", "FULL", "BIDIRECTIONAL"),
            "B06": ("T", "FULL", "BIDIRECTIONAL"),
            "B07": ("NECK", "DUAL_CLUSTER", "BIDIRECTIONAL"),
            "B08": ("RECT", "CHAIN", "BIDIRECTIONAL"),
            "B09": ("RECT", "FULL", "SPLIT_ENTRY_EXIT"),
        }[scene_id]
        return generate_topology_trial_design(
            LayoutExplorationCase(
                suite_id="PM028-E5-DESIGN",
                case_id=f"E5-DESIGN-{scene_id}",
                generator_version="replay_browser_trial.v1",
                expected_class="VALID",
                factors={
                    "footprint": factors[0],
                    "vertical": factors[1],
                    "fare": factors[2],
                    "mirror": False,
                    "level_count": 3,
                },
                seed=20261000 + int(scene_id[1:]),
            )
        )

    recipes = {
        "B01": LayoutRecipe("e5-b01", 20261001, "single_terminal", 2, 1, 0, 0, 0, False, "sparse", 0),
        "B02": LayoutRecipe("e5-b02", 20261002, "two_level_island", 2, 1, 1, 1, 1, False, "standard", 2),
        "B03": LayoutRecipe("e5-b03", 20261003, "two_level_multi_access", 3, 2, 3, 1, 1, False, "dense", 4),
        "B04": LayoutRecipe("e5-b04", 20261004, "three_level_transfer", 4, 2, 6, 1, 1, True, "dense", 8),
        "B10": LayoutRecipe("e5-b10", 20261010, "two_level_island", 2, 2, 3, 1, 1, False, "standard", 3),
        "B11": LayoutRecipe("e5-b11", 20261011, "single_terminal", 2, 1, 0, 0, 0, False, "standard", 5),
        "B12": LayoutRecipe("e5-b12", 20261012, "two_level_island", 2, 1, 1, 1, 1, False, "standard", 6),
    }
    document = generate_layout(recipes[scene_id])
    if scene_id == "B11":
        document = _with_mixed_geometry(document)
    if scene_id == "B12":
        document = _with_rotated_rect(document)
    return document


def _scenario(scene_id: str, document) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"PM-028 E5 {scene_id}",
        hour=18,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="pm028_e5_browser",
        sample_hours=1,
        station_design=document,
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )


def _with_mixed_geometry(document):
    level = min(document.levels, key=lambda item: item.order)
    additions = (
        DesignElement(
            id="browser_polygon",
            kind="equipment",
            level_id=level.id,
            geometry=ElementGeometry(
                "polygon",
                points_m=((48.0, 13.0), (55.0, 11.0), (58.0, 18.0), (50.0, 19.0)),
            ),
            label="Browser polygon",
            role="decoration",
            movable=False,
            resizable=False,
            metadata={"presentation_only": True, "blocking": False},
        ),
        DesignElement(
            id="browser_polyline",
            kind="equipment",
            level_id=level.id,
            geometry=ElementGeometry(
                "polyline",
                points_m=((15.0, 14.0), (25.0, 11.0), (34.0, 17.0)),
            ),
            label="Browser polyline",
            role="decoration",
            movable=False,
            resizable=False,
            metadata={"presentation_only": True, "blocking": False},
        ),
        DesignElement(
            id="browser_point",
            kind="equipment",
            level_id=level.id,
            geometry=ElementGeometry("point", x_m=42.0, y_m=15.0),
            label="Browser point",
            role="decoration",
            movable=False,
            resizable=False,
            metadata={"presentation_only": True, "blocking": False},
        ),
    )
    return generate_station(replace(document, elements=(*document.elements, *additions)))


def _with_rotated_rect(document):
    candidate = next(
        element
        for element in document.elements
        if element.geometry.shape == "rect" and element.role not in {"floor", "vertical_connector"}
    )
    rotated = replace(
        candidate,
        geometry=replace(candidate.geometry, rotation_deg=30.0),
        metadata={**candidate.metadata, "browser_rotation_probe": True},
    )
    return generate_station(
        replace(
            document,
            elements=tuple(rotated if item.id == candidate.id else item for item in document.elements),
        )
    )


def _damaged_frontend_manifest(payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    damaged = deepcopy(payload)
    first, second, *remaining = damaged["bindings"]
    second["asset_id"] = "unknown:asset:v1"
    damaged["bindings"] = [second, *remaining]
    return damaged, ("asset_binding_missing", "asset_binding_unresolved")


def _rotated_entity_id(scene_payload: dict[str, Any]) -> str:
    return next(
        str(entity["entity_id"])
        for entity in scene_payload["entities"]
        if entity.get("metadata", {}).get("browser_rotation_probe") is True
    )


def _placement_override(manifest: AssetManifest, entity_id: str) -> AssetManifest:
    bindings = tuple(
        replace(
            binding,
            placement={
                **dict(binding.placement),
                "scale": [1.2, 0.8],
                "rotation_deg": 15.0,
                "offset_m": [1.0, -0.5],
            },
        )
        if binding.scene_entity_id == entity_id
        else binding
        for binding in manifest.bindings
    )
    return replace(manifest, bindings=bindings)
