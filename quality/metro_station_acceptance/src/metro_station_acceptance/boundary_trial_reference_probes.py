from __future__ import annotations

from dataclasses import replace

from metro_station.application.replay import AssetManifest, ReplayPackage, StationScene
from metro_station.adapters.simulation.compilation.validation import validate_station_design
from metro_station.adapters.simulation.simulation_outputs.station_scene import (
    compile_procedural_asset_manifest,
    compile_station_scene,
)
from metro_station.adapters.simulation.station.compiler import DesignCompiler
from metro_station.adapters.simulation.station.scenario import StationSandboxScenario

from .boundary_trial_baseline import boundary_baseline


REFERENCE_CODES = {
    "DUPLICATE_SCENE_ENTITY": "scene.duplicate_entity_id",
    "DUPLICATE_RUNTIME_BINDING": "scene.duplicate_runtime_id",
    "DUPLICATE_ASSET_BINDING": "asset.duplicate_binding_id",
    "RUNTIME_UNKNOWN_ENTITY": "scene.runtime_unknown_entity",
    "ASSET_UNKNOWN_ASSET": "asset.unknown_asset",
    "ASSET_UNKNOWN_ENTITY": "asset.unknown_entity",
    "DUPLICATE_RUNTIME_ID": "scene.duplicate_runtime_id",
    "FINGERPRINT_TAMPER": "contract.fingerprint_mismatch",
    "POINTER_EXTERNAL": "replay.pointer_not_local",
    "POINTER_INVALID": "replay.pointer_not_local",
}


def run_reference_probe(variant: str) -> tuple[bool, tuple[str, ...]]:
    if variant not in REFERENCE_CODES:
        return _design_reference_probe(variant)
    try:
        _exercise_replay_reference(variant)
    except (TypeError, ValueError, KeyError):
        return False, (REFERENCE_CODES[variant],)
    return True, ()


def _design_reference_probe(variant: str) -> tuple[bool, tuple[str, ...]]:
    document = boundary_baseline()
    if variant == "DUPLICATE_LEVEL":
        document = replace(document, levels=(*document.levels, document.levels[0]))
    elif variant == "DUPLICATE_ELEMENT":
        document = replace(document, elements=(*document.elements, document.elements[0]))
    elif variant == "DUPLICATE_QUEUE":
        document = replace(document, queues=(*document.queues, document.queues[0]))
    elif variant == "DUPLICATE_CONNECTION":
        document = replace(document, connections=(*document.connections, document.connections[0]))
    elif variant == "DUPLICATE_PORT":
        element = next(item for item in document.elements if item.ports)
        changed = replace(element, ports=(*element.ports, element.ports[0]))
        document = replace(
            document,
            elements=tuple(changed if item.id == element.id else item for item in document.elements),
        )
    elif variant == "CONNECTION_UNKNOWN_ELEMENT":
        first = replace(document.connections[0], source_id="missing_element")
        document = replace(document, connections=(first, *document.connections[1:]))
    elif variant == "CONNECTION_UNKNOWN_PORT":
        first = replace(document.connections[0], source_port_id="missing_port")
        document = replace(document, connections=(first, *document.connections[1:]))
    elif variant == "QUEUE_UNKNOWN_OWNER":
        first = replace(document.queues[0], owner_element_id="missing_owner")
        document = replace(document, queues=(first, *document.queues[1:]))
    else:
        connector = next(item for item in document.elements if item.role == "vertical_connector")
        changed = replace(connector, connects_levels=(*connector.connects_levels, "missing_level"))
        document = replace(
            document,
            elements=tuple(changed if item.id == connector.id else item for item in document.elements),
        )
    issues = validate_station_design(document)
    return not any(issue.severity == "error" for issue in issues), tuple(
        issue.code for issue in issues
    )


def _exercise_replay_reference(variant: str) -> None:
    scene, manifest = _scene_and_manifest()
    if variant == "DUPLICATE_SCENE_ENTITY":
        replace(scene, entities=(*scene.entities, scene.entities[0]))
        return
    if variant in {"DUPLICATE_RUNTIME_BINDING", "DUPLICATE_RUNTIME_ID"}:
        replace(scene, runtime_bindings=(*scene.runtime_bindings, scene.runtime_bindings[0]))
        return
    if variant == "DUPLICATE_ASSET_BINDING":
        replace(manifest, bindings=(*manifest.bindings, manifest.bindings[0]))
        return
    if variant == "RUNTIME_UNKNOWN_ENTITY":
        bad = replace(scene.runtime_bindings[0], scene_entity_id="missing_entity")
        replace(scene, runtime_bindings=(bad, *scene.runtime_bindings[1:]))
        return
    if variant == "ASSET_UNKNOWN_ASSET":
        bad = replace(manifest.bindings[0], asset_id="missing_asset")
        replace(manifest, bindings=(bad, *manifest.bindings[1:]))
        return
    if variant == "ASSET_UNKNOWN_ENTITY":
        bad = replace(manifest.bindings[0], scene_entity_id="missing_entity")
        changed = replace(manifest, bindings=(bad, *manifest.bindings[1:]))
        ReplayPackage("boundary", scene, changed)
        return
    if variant == "FINGERPRINT_TAMPER":
        payload = scene.as_dict()
        payload["semantic_fingerprint"] = "tampered"
        StationScene.from_dict(payload)
        return
    pointer = "https://example.invalid/trace" if variant == "POINTER_EXTERNAL" else "invalid"
    ReplayPackage("boundary", scene, manifest, simulation_trace_ref=pointer)


def _scene_and_manifest() -> tuple[StationScene, AssetManifest]:
    design = boundary_baseline()
    scenario = StationSandboxScenario(
        station_name="boundary_reference",
        hour=18,
        minutes=1,
        tick_seconds=5,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="boundary_trial",
        sample_hours=1,
        station_design=design,
        simulation_clock_mode="physical",
        goal_graph_mode="active",
        audit_enabled=False,
        audit_print_events=False,
    )
    layout = DesignCompiler.compile(design, scenario)
    scene = compile_station_scene(scenario, layout.facilities)
    return scene, compile_procedural_asset_manifest(scene)
