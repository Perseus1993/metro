from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from metro_station.application.replay import AssetManifest, StationScene
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario


@dataclass(frozen=True)
class GeneratedReplayContractReport:
    design_id: str
    level_count: int
    scene_entity_count: int
    scene_relation_count: int
    facility_count: int
    runtime_binding_count: int
    asset_count: int
    asset_binding_count: int
    elevator_entity_count: int
    checks: dict[str, bool]

    @property
    def status(self) -> str:
        return "ok" if self.checks and all(self.checks.values()) else "review"

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, **asdict(self)}


def inspect_generated_replay_contract(
    document: StationDesignDocument,
) -> GeneratedReplayContractReport:
    scenario = _contract_scenario(document)
    layout = DesignCompiler.compile(document, scenario)
    scene = compile_station_scene(scenario, layout.facilities)
    manifest = compile_procedural_asset_manifest(scene)
    entity_ids = {entity.entity_id for entity in scene.entities}
    runtime_ids = {binding.runtime_id for binding in scene.runtime_bindings}
    asset_ids = {asset.asset_id for asset in manifest.assets}
    physical_count = len(document.elements) + len(document.queues)
    restored_scene = StationScene.from_dict(scene.as_dict())
    restored_manifest = AssetManifest.from_dict(manifest.as_dict())
    checks = {
        "scene_level_count_matches_design": len(scene.levels) == len(document.levels),
        "physical_entities_mapped_once": len(scene.entities) == physical_count
        and len(entity_ids) == physical_count,
        "all_facilities_bound": len(scene.runtime_bindings) == len(layout.facilities),
        "runtime_ids_unique": len(runtime_ids) == len(scene.runtime_bindings),
        "runtime_scene_references_resolve": all(
            binding.scene_entity_id in entity_ids for binding in scene.runtime_bindings
        ),
        "asset_references_resolve": all(
            binding.scene_entity_id in entity_ids and binding.asset_id in asset_ids
            for binding in manifest.bindings
        ),
        "assets_bind_every_entity": {binding.scene_entity_id for binding in manifest.bindings}
        == entity_ids,
        "scene_round_trip_stable": restored_scene.as_dict() == scene.as_dict(),
        "asset_manifest_round_trip_stable": restored_manifest.as_dict() == manifest.as_dict(),
    }
    return GeneratedReplayContractReport(
        design_id=document.id,
        level_count=len(scene.levels),
        scene_entity_count=len(scene.entities),
        scene_relation_count=len(scene.relations),
        facility_count=len(layout.facilities),
        runtime_binding_count=len(scene.runtime_bindings),
        asset_count=len(manifest.assets),
        asset_binding_count=len(manifest.bindings),
        elevator_entity_count=sum(entity.kind == "elevator" for entity in scene.entities),
        checks=checks,
    )


def _contract_scenario(document: StationDesignDocument) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"generated_replay_{document.id}",
        hour=18,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        transfer_count_hour=0,
        source_label="generated_layout_acceptance",
        sample_hours=1,
        station_design=document,
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )
