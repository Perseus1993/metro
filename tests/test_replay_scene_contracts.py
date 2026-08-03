from __future__ import annotations

from dataclasses import replace
import unittest

from metro_station.application.replay import ReplayPackage
from metro_station.adapters.simulation.design.schema import DesignConnection
from metro_station.adapters.simulation.design.station_generation import generate_station
from metro_station.adapters.simulation.design.templates import create_design
from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station_experiments.runner import ExperimentCase, scenario_from_case


class ReplaySceneContractTests(unittest.TestCase):
    def test_three_physical_elevators_map_six_runtime_facilities(self) -> None:
        design = _three_elevator_design()
        case = ExperimentCase(
            case_id="three_elevator_scene",
            design=design,
            design_label="three_elevator_scene",
            entry_count_hour=0,
            exit_count_hour=0,
        )
        scenario = scenario_from_case(case)
        layout = DesignCompiler.compile(design, scenario)

        scene = compile_station_scene(scenario, layout.facilities)
        manifest = compile_procedural_asset_manifest(scene)

        elevator_entities = [item for item in scene.entities if item.kind == "elevator"]
        elevator_bindings = [item for item in scene.runtime_bindings if item.kind == "elevator"]
        self.assertEqual(3, len(elevator_entities))
        self.assertEqual(6, len(elevator_bindings))
        self.assertEqual(6, len({item.runtime_id for item in elevator_bindings}))
        self.assertEqual(
            {item.entity_id for item in elevator_entities},
            {item.scene_entity_id for item in elevator_bindings},
        )
        self.assertTrue(all(len(item.level_ids) == 2 for item in elevator_entities))

        elevator_asset = next(item for item in manifest.assets if item.semantic_kind == "elevator")
        elevator_asset_bindings = [
            item for item in manifest.bindings if item.asset_id == elevator_asset.asset_id
        ]
        self.assertEqual(3, len(elevator_asset_bindings))

        package = ReplayPackage(
            source_run_id="run-three-elevators",
            station_scene=scene,
            asset_manifest=manifest,
        )
        restored = ReplayPackage.from_dict(package.as_dict())
        self.assertEqual(package.semantic_fingerprint, restored.semantic_fingerprint)


def _three_elevator_design():
    base = create_design("two_level_island_platform")
    elevator = next(item for item in base.elements if item.id == "elevator_a")
    elevator_b = replace(
        elevator,
        id="elevator_b",
        label="Elevator B",
        geometry=elevator.geometry.moved_to(75.0, 32.0),
        ports=(),
    )
    elevator_c = replace(
        elevator,
        id="elevator_c",
        label="Elevator C",
        geometry=elevator.geometry.moved_to(84.0, 32.0),
        ports=(),
    )
    connections = (
        *base.connections,
        DesignConnection("conn_gates_to_elevator_b", "gate_bank_a", "elevator_b", "walk"),
        DesignConnection(
            "conn_elevator_b_to_platform",
            "elevator_b",
            "b2_platform_floor",
            "vertical",
        ),
        DesignConnection("conn_gates_to_elevator_c", "gate_bank_a", "elevator_c", "walk"),
        DesignConnection(
            "conn_elevator_c_to_platform",
            "elevator_c",
            "b2_platform_floor",
            "vertical",
        ),
    )
    return generate_station(
        replace(
            base,
            id="station_design_three_elevators",
            label="Three-elevator station design",
            elements=(*base.elements, elevator_b, elevator_c),
            connections=connections,
        )
    )


if __name__ == "__main__":
    unittest.main()
