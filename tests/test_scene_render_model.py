from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest

from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_visualizer.config import ASSET_DIR
from metro_station_testkit.layout_recipe import LayoutRecipe
from metro_station_testkit.layout_scenario_generator import generate_layout


SCENE_RENDER_MODEL_JS = ASSET_DIR / "scene_render_model.js"


@unittest.skipIf(shutil.which("node") is None, "node is required for JS scene checks")
class SceneRenderModelTests(unittest.TestCase):
    def test_scene_model_places_three_elevators_and_maps_six_runtime_ids(self) -> None:
        entities = [
            {
                "entity_id": f"element:elevator_{suffix}",
                "kind": "elevator",
                "label": f"Elevator {suffix.upper()}",
                "level_ids": ["b1", "b2"],
                "geometry": {
                    "shape": "rect",
                    "x_m": x,
                    "y_m": 20,
                    "width_m": 6,
                    "height_m": 6,
                },
            }
            for suffix, x in (("a", 20), ("b", 40), ("c", 60))
        ]
        runtime_bindings = [
            {
                "runtime_id": f"vertical:elevator_{suffix}:{direction}:b1:b2",
                "scene_entity_id": f"element:elevator_{suffix}",
            }
            for suffix in ("a", "b", "c")
            for direction in ("up", "down")
        ]
        scene = {
            "schema_version": "station_scene.v1",
            "scene_id": "three-elevators",
            "coordinate_system": {"width": 100, "height": 50},
            "levels": [{"level_id": "b1"}, {"level_id": "b2"}],
            "entities": entities,
            "relations": [],
            "runtime_bindings": runtime_bindings,
        }
        manifest = {
            "assets": [{"asset_id": "procedural:elevator:v1"}],
            "bindings": [
                {
                    "binding_id": f"asset-binding:{entity['entity_id']}",
                    "scene_entity_id": entity["entity_id"],
                    "asset_id": "procedural:elevator:v1",
                    "placement": {"mode": "fit_geometry"},
                }
                for entity in entities
            ],
        }
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const {{ buildSceneRenderModel }} = require({json.dumps(str(SCENE_RENDER_MODEL_JS))});
            const model = buildSceneRenderModel(
              {json.dumps(scene)},
              {json.dumps(manifest)},
              1000,
              500,
            );
            assert.equal(model.elevatorEntities.length, 3);
            assert.equal(Object.keys(model.runtimeToEntity).length, 6);
            assert.equal(model.runtimeBindings.length, 6);
            assert.notDeepEqual(
              model.runtimeBindings[0].position,
              model.runtimeBindings[0].exitPosition,
            );
            assert.equal(model.elevatorEntities[0].boundsPx.w, 60);
            assert.equal(model.diagnostics.length, 0);
            """
        )

        subprocess.run(["node"], input=script, text=True, check=True)

    def test_rotation_point_geometry_and_asset_placement_are_applied(self) -> None:
        scene = {
            "schema_version": "station_scene.v1",
            "scene_id": "geometry-placement",
            "coordinate_system": {"width": 100, "height": 50},
            "levels": [{"level_id": "b1"}],
            "entities": [
                {
                    "entity_id": "element:rotated",
                    "kind": "equipment",
                    "level_ids": ["b1"],
                    "geometry": {
                        "shape": "rect",
                        "x_m": 10,
                        "y_m": 10,
                        "width_m": 20,
                        "height_m": 10,
                        "rotation_deg": 90,
                    },
                },
                {
                    "entity_id": "element:point",
                    "kind": "equipment",
                    "level_ids": ["b1"],
                    "geometry": {"shape": "point", "x_m": 5, "y_m": 7},
                },
            ],
            "relations": [],
            "runtime_bindings": [],
        }
        manifest = {
            "assets": [{"asset_id": "procedural:equipment:v1"}],
            "bindings": [
                {
                    "binding_id": "binding:rotated",
                    "scene_entity_id": "element:rotated",
                    "asset_id": "procedural:equipment:v1",
                    "placement": {
                        "mode": "fit_geometry",
                        "scale": [2, 1],
                        "rotation_deg": 90,
                        "offset_m": [3, -2],
                    },
                },
                {
                    "binding_id": "binding:point",
                    "scene_entity_id": "element:point",
                    "asset_id": "procedural:equipment:v1",
                    "placement": {"mode": "fit_geometry"},
                },
            ],
        }
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const {{ buildSceneRenderModel }} = require({json.dumps(str(SCENE_RENDER_MODEL_JS))});
            const model = buildSceneRenderModel(
              {json.dumps(scene)},
              {json.dumps(manifest)},
              1000,
              500,
            );
            const rotated = model.entityById["element:rotated"];
            assert.equal(rotated.rotationDeg, 90);
            assert.equal(rotated.placementRotationDeg, 90);
            assert.ok(Math.abs(rotated.center[0] - 230) < 1e-8);
            assert.ok(Math.abs(rotated.center[1] - 130) < 1e-8);
            assert.ok(Math.abs(rotated.boundsPx.w - 200) < 1e-8);
            assert.ok(Math.abs(rotated.boundsPx.h - 200) < 1e-8);
            assert.deepEqual(model.entityById["element:point"].center, [50, 70]);
            assert.deepEqual(model.diagnostics, []);
            """
        )

        subprocess.run(["node"], input=script, text=True, check=True)

    def test_generated_three_level_six_elevator_scene_has_no_display_diagnostics(self) -> None:
        design = generate_layout(_generated_six_elevator_recipe())
        scenario = StationSandboxScenario(
            station_name="generated_scene_render_model",
            hour=18,
            minutes=1,
            tick_seconds=5,
            group_size=1,
            entry_count_hour=0,
            exit_count_hour=0,
            transfer_count_hour=0,
            source_label="generated_scene_test",
            sample_hours=1,
            station_design=design,
            simulation_clock_mode="physical",
            goal_graph_mode="active",
            audit_enabled=False,
            audit_print_events=False,
        )
        layout = DesignCompiler.compile(design, scenario)
        scene = compile_station_scene(scenario, layout.facilities)
        manifest = compile_procedural_asset_manifest(scene)
        elevator_binding_count = sum(
            binding.kind == "elevator" for binding in scene.runtime_bindings
        )
        script = textwrap.dedent(
            f"""
            const assert = require("assert");
            const {{ buildSceneRenderModel }} = require({json.dumps(str(SCENE_RENDER_MODEL_JS))});
            const model = buildSceneRenderModel(
              {json.dumps(scene.as_dict())},
              {json.dumps(manifest.as_dict())},
              1200,
              800,
            );
            assert.equal(model.levels.length, 3);
            assert.equal(model.elevatorEntities.length, 6);
            assert.equal(
              model.runtimeBindings.filter((item) => item.kind === "elevator").length,
              {elevator_binding_count},
            );
            assert.equal(model.entities.length, {len(design.elements) + len(design.queues)});
            assert.deepEqual(model.diagnostics, []);
            """
        )

        subprocess.run(["node"], input=script, text=True, check=True)


def _generated_six_elevator_recipe() -> LayoutRecipe:
    return LayoutRecipe(
        recipe_id="render-three-level-six-elevators",
        seed=73,
        archetype="three_level_transfer",
        entrance_count=4,
        gate_count=2,
        elevator_count=6,
        stairs_count=1,
        escalator_pair_count=1,
        mirror=True,
        asset_density="dense",
        geometry_variant=8,
        operation_profile="train_outage",
    )


if __name__ == "__main__":
    unittest.main()
