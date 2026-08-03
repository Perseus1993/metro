from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from metro_station.application.replay import AssetManifest, StationScene
from metro_station.application.semantic_fingerprints import semantic_fingerprint
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.graph import StationGraph
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario
from metro_station_testkit.instant_movement_backend import InstantMovementBackend
from metro_station_testkit.layout_quality import LayoutQualityReport, inspect_layout_quality


@dataclass(frozen=True)
class MetamorphicArtifacts:
    document: StationDesignDocument
    quality: LayoutQualityReport
    graph: StationGraph
    scene: StationScene
    manifest: AssetManifest
    runtime_summary: dict[str, Any]
    runtime_fingerprint: str
    entrance_weights: tuple[tuple[str, float], ...]


def build_metamorphic_artifacts(
    document: StationDesignDocument,
    *,
    seed: int,
    entrance_weights: tuple[tuple[str, float], ...] | None = None,
) -> MetamorphicArtifacts:
    weights = default_entrance_weights(document) if entrance_weights is None else entrance_weights
    scenario = _scenario(document, weights)
    quality = inspect_layout_quality(document)
    layout = DesignCompiler.compile(document, scenario)
    graph = layout.station_graph
    scene = compile_station_scene(scenario, layout.facilities)
    manifest = compile_procedural_asset_manifest(scene)
    model = MetroStationModel(
        scenario,
        seed=seed,
        movement_backend=InstantMovementBackend(),
    )
    frames = model.run()
    graph_events = Counter(
        event.kind for event in model.goal_parity.events if event.stream == "graph"
    )
    summary = {
        "spawned_persons": model.spawned_persons,
        "terminal_persons": sum(event.persons for event in model.passenger_terminal_events),
        "remaining_persons": int(frames[-1]["metrics"]["station_persons"]),
        "max_person_accounting_error": max(
            abs(
                int(frame["metrics"]["spawned_persons"])
                - int(frame["metrics"]["station_persons"])
                - int(frame["metrics"]["departed_persons"])
            )
            for frame in frames
        ),
        "terminal_graph_events": int(graph_events["terminal_reached"]),
        "graph_event_kinds": sorted(graph_events),
        "entrance_person_counts": sorted(model.spawned_persons_by_entrance.values()),
    }
    return MetamorphicArtifacts(
        document,
        quality,
        graph,
        scene,
        manifest,
        summary,
        semantic_fingerprint(summary),
        weights,
    )


def default_entrance_weights(
    document: StationDesignDocument,
) -> tuple[tuple[str, float], ...]:
    entrances = sorted(element.id for element in document.elements if element.kind == "entrance")
    if len(entrances) < 2:
        return ()
    return ((entrances[0], 0.75), (entrances[1], 0.25))


def mirrored_entrance_weights(
    document: StationDesignDocument,
) -> tuple[tuple[str, float], ...]:
    weights = default_entrance_weights(document)
    return tuple(
        (element_id, weight) for (element_id, _), (_, weight) in zip(weights, reversed(weights))
    )


def replay_integrity(artifacts: MetamorphicArtifacts) -> bool:
    entity_ids = {entity.entity_id for entity in artifacts.scene.entities}
    asset_ids = {asset.asset_id for asset in artifacts.manifest.assets}
    return (
        all(binding.scene_entity_id in entity_ids for binding in artifacts.scene.runtime_bindings)
        and all(
            binding.scene_entity_id in entity_ids and binding.asset_id in asset_ids
            for binding in artifacts.manifest.bindings
        )
        and {binding.scene_entity_id for binding in artifacts.manifest.bindings} == entity_ids
    )


def binding_projection(artifacts: MetamorphicArtifacts) -> set[tuple[Any, ...]]:
    return {
        (
            item.runtime_id,
            item.scene_entity_id,
            item.kind,
            item.stage,
            item.direction,
            item.entry_level_id,
            item.exit_level_id,
        )
        for item in artifacts.scene.runtime_bindings
    }


def entity_projection(artifacts: MetamorphicArtifacts) -> set[tuple[Any, ...]]:
    return {
        (item.entity_id, item.kind, item.level_ids, item.source_element_id)
        for item in artifacts.scene.entities
        if item.source_element_id != "presentation_marker"
    }


def _scenario(
    document: StationDesignDocument,
    entrance_weights: tuple[tuple[str, float], ...],
) -> StationSandboxScenario:
    return StationSandboxScenario(
        station_name=f"metamorphic_{document.id}",
        hour=8,
        minutes=12,
        demand_minutes=1,
        tick_seconds=5,
        group_size=5,
        entry_count_hour=300,
        exit_count_hour=120,
        transfer_count_hour=0,
        entry_entrance_weights=entrance_weights,
        source_label="PM-028-E4",
        sample_hours=1,
        station_design=document,
        train_headway_seconds=60,
        train_dwell_seconds=30,
        initial_train_offset_seconds=15,
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
