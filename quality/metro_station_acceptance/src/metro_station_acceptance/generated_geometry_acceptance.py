from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from multiprocessing import get_context
from queue import Empty
from typing import Any

from metro_station.adapters.simulation.compilation.validation import (
    validate_compiled_station_design,
)
from metro_station.adapters.simulation.design import create_design, topology_templates
from metro_station.adapters.simulation.design.schema import StationDesignDocument
from metro_station_testkit.layout_corpus import generate_geometry_scenario_matrix
from metro_station_testkit.layout_recipe import (
    ARCHETYPES,
    FARE_TOPOLOGIES,
    TOPOLOGY_FOOTPRINTS,
    VERTICAL_TOPOLOGIES,
)
from metro_station_testkit.layout_scenario_generator import generate_layout

from .generated_replay_contract import generated_contract_scenario
from .capacity_convergence_acceptance import inspect_capacity_convergence


GEOMETRY_MATRIX_SCHEMA_VERSION = "generated_geometry_matrix.v1"
GEOMETRY_RUNTIME_BUDGET_SECONDS = 120.0
GEOMETRY_MATRIX_SEEDS = (7, 42)
GEOMETRY_RECIPE_COUNT = 240
GEOMETRY_REQUESTED_CELL_COUNT = 120
GEOMETRY_FEASIBLE_SEEDED_CELL_COUNT = 160
GEOMETRY_NORMALIZATION_PROBE_COUNT = 80
GEOMETRY_MIN_UNIQUE_PHYSICAL_LAYOUTS = GEOMETRY_FEASIBLE_SEEDED_CELL_COUNT
GEOMETRY_MAX_PHYSICAL_CLONE_GROUP = len(VERTICAL_TOPOLOGIES)
# Geometry compilation is CPU-bound and each recipe is process-isolated.  A
# four-process cap left most modern workstation cores idle and made the fixed
# 240-recipe gate miss its wall budget even after algorithmic hot spots were
# removed.  Twelve stays below the 14 physical cores of the reference runner,
# leaves headroom for the coordinator, and scales down automatically on small
# CI hosts.
GEOMETRY_COMPILE_WORKERS = max(1, min(12, os.cpu_count() or 1))


def run_generated_geometry_acceptance() -> dict[str, Any]:
    started = time.perf_counter()
    corpus = generate_geometry_scenario_matrix()
    capacity_convergence = inspect_capacity_convergence()
    templates = tuple(
        _inspect_document(create_design(template.id), case_id=template.id)
        for template in topology_templates()
    )
    remaining_budget = max(
        0.001,
        GEOMETRY_RUNTIME_BUDGET_SECONDS - (time.perf_counter() - started),
    )
    records, unfinished_recipe_ids = _inspect_recipes(
        corpus.recipes,
        timeout_seconds=remaining_budget,
    )
    elapsed = time.perf_counter() - started
    failed = tuple(record for record in records if record["status"] != "ok")
    requested_cells = Counter(
        (
            record.get("archetype"),
            record.get("topology_footprint"),
            record.get("requested_vertical_topology"),
            record.get("fare_topology"),
        )
        for record in records
    )
    effective_seeded_cells = Counter(
        (
            record.get("archetype"),
            record.get("topology_footprint"),
            record.get("effective_vertical_topology"),
            record.get("fare_topology"),
            record.get("seed"),
        )
        for record in records
    )
    expected_requested = _expected_requested_cells()
    expected_effective_seeded = _expected_effective_seeded_cells()
    fingerprints = tuple(
        record.get("geometry_fingerprint")
        for record in records
        if record.get("geometry_fingerprint") is not None
    )
    fingerprint_counts = Counter(fingerprints)
    largest_clone_group = max(fingerprint_counts.values(), default=0)
    normalization_probe_count = sum(
        record.get("requested_vertical_topology")
        != record.get("effective_vertical_topology")
        for record in records
    )
    checks = {
        "four_formal_templates_pass": len(templates) == 4
        and all(record["status"] == "ok" for record in templates),
        "matrix_has_240_recipes": len(records) == GEOMETRY_RECIPE_COUNT,
        "matrix_recipe_ids_unique": len({record["recipe_id"] for record in records})
        == len(records),
        "matrix_requested_cells_exactly_twice": requested_cells
        == expected_requested
        and len(requested_cells) == GEOMETRY_REQUESTED_CELL_COUNT,
        "matrix_has_160_feasible_seeded_cells": effective_seeded_cells
        == expected_effective_seeded
        and len(effective_seeded_cells) == GEOMETRY_FEASIBLE_SEEDED_CELL_COUNT,
        "matrix_has_80_explicit_normalization_probes": normalization_probe_count
        == GEOMETRY_NORMALIZATION_PROBE_COUNT,
        "matrix_has_at_least_160_unique_physical_layouts": len(fingerprints)
        == len(records)
        and len(set(fingerprints)) >= GEOMETRY_MIN_UNIQUE_PHYSICAL_LAYOUTS,
        "matrix_physical_clone_groups_within_normalization_budget": len(
            fingerprints
        )
        == len(records)
        and largest_clone_group <= GEOMETRY_MAX_PHYSICAL_CLONE_GROUP,
        "all_generated_recipes_compile": not failed,
        "all_facilities_have_unique_bindings": all(
            record.get("facility_binding_rate") == 1.0 for record in records
        ),
        "capacity_convergence_gate_passes": capacity_convergence["status"] == "ok",
        "runtime_within_120_seconds": elapsed <= GEOMETRY_RUNTIME_BUDGET_SECONDS,
        "matrix_completed_before_deadline": not unfinished_recipe_ids,
    }
    return {
        "schema_version": GEOMETRY_MATRIX_SCHEMA_VERSION,
        "status": "ok" if all(checks.values()) else "review",
        "templates": templates,
        "corpus_id": corpus.corpus_id,
        "recipe_count": len(records),
        "failed_recipes": tuple(
            {
                "recipe_id": record["recipe_id"],
                "seed": record["seed"],
            }
            for record in failed
        ),
        "unfinished_recipe_ids": unfinished_recipe_ids,
        "timeout_reason": (
            None
            if not unfinished_recipe_ids
            else (
                "geometry_worker_crashed"
                if any(
                    "GeometryWorkerCrashed" in record.get("error_codes", ())
                    for record in records
                )
                else "geometry_runtime_budget_exhausted"
            )
        ),
        "metrics": {
            "wall_seconds": round(elapsed, 6),
            "requested_cell_count": len(requested_cells),
            "effective_seeded_cell_count": len(effective_seeded_cells),
            "normalization_probe_count": normalization_probe_count,
            "unique_geometry_fingerprint_count": len(set(fingerprints)),
            "largest_geometry_clone_group": largest_clone_group,
            "error_code_counts": dict(
                sorted(
                    Counter(
                        code
                        for record in failed
                        for code in record.get("error_codes", ())
                    ).items()
                )
            ),
        },
        "capacity_convergence": capacity_convergence,
        "checks": checks,
    }


def _inspect_recipes(
    recipes,
    *,
    timeout_seconds: float,
    worker=None,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """Compile recipes in isolated workers under the gate's wall-clock budget."""

    recipe_list = tuple(recipes)
    if not recipe_list:
        return [], ()
    deadline = time.perf_counter() + max(0.0, float(timeout_seconds))
    inspect_worker = _inspect_recipe if worker is None else worker
    context = get_context("spawn")
    task_queue = context.Queue()
    result_queue = context.Queue()
    process_count = min(GEOMETRY_COMPILE_WORKERS, len(recipe_list))
    processes = tuple(
        context.Process(
            target=_geometry_worker_loop,
            args=(task_queue, result_queue, inspect_worker),
        )
        for _ in range(process_count)
    )
    for process in processes:
        process.start()
    for index, recipe in enumerate(recipe_list):
        task_queue.put((index, recipe))
    for _ in processes:
        task_queue.put(None)

    records_by_index: dict[int, dict[str, Any]] = {}
    active_index_by_pid: dict[int, int] = {}
    crashed_processes: dict[int, int] = {}
    while len(records_by_index) < len(recipe_list):
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            break
        try:
            message = result_queue.get(timeout=min(remaining, 0.05))
        except Empty:
            for process in processes:
                if process.exitcode not in {None, 0} and process.pid is not None:
                    crashed_processes[int(process.pid)] = int(process.exitcode)
            if crashed_processes:
                break
            continue
        kind = str(message[0])
        if kind == "started":
            _, pid, index, _recipe_id = message
            active_index_by_pid[int(pid)] = int(index)
            continue
        if kind != "result":
            raise RuntimeError(f"unknown geometry worker message {kind!r}")
        _, pid, index, record = message
        active_index_by_pid.pop(int(pid), None)
        records_by_index[int(index)] = record

    unfinished_indices = tuple(
        index for index in range(len(recipe_list)) if index not in records_by_index
    )
    _stop_geometry_workers(processes, force=bool(unfinished_indices))
    task_queue.close()
    result_queue.close()
    if unfinished_indices:
        task_queue.cancel_join_thread()
        result_queue.cancel_join_thread()
    else:
        task_queue.join_thread()
        result_queue.join_thread()

    for index in unfinished_indices:
        recipe = recipe_list[index]
        crashed_assignment = next(
            (
                (pid, crashed_processes[pid])
                for pid, active_index in active_index_by_pid.items()
                if active_index == index and pid in crashed_processes
            ),
            None,
        )
        if crashed_assignment is None and crashed_processes:
            crashed_assignment = next(iter(crashed_processes.items()))
        worker_crashed = bool(crashed_processes)
        error_code = (
            "GeometryWorkerCrashed"
            if worker_crashed
            else "GeometryAcceptanceTimeout"
        )
        error = (
            "geometry worker crashed"
            + (
                ""
                if crashed_assignment is None
                else (
                    f": pid={crashed_assignment[0]} "
                    f"exitcode={crashed_assignment[1]}"
                )
            )
            if worker_crashed
            else "geometry acceptance runtime budget exhausted"
        )
        records_by_index[index] = {
            "status": "review",
            "case_id": recipe.recipe_id,
            "recipe_id": recipe.recipe_id,
            "seed": recipe.seed,
            "error_codes": (error_code,),
            "error": error,
        }
    return (
        [records_by_index[index] for index in range(len(recipe_list))],
        tuple(recipe_list[index].recipe_id for index in unfinished_indices),
    )


def _geometry_worker_loop(task_queue, result_queue, worker) -> None:
    while True:
        task = task_queue.get()
        if task is None:
            return
        index, recipe = task
        pid = os.getpid()
        result_queue.put(("started", pid, index, recipe.recipe_id))
        try:
            record = worker(recipe)
        except Exception as exc:
            record = _failed_recipe_record(recipe, exc)
        result_queue.put(("result", pid, index, record))


def _stop_geometry_workers(processes, *, force: bool) -> None:
    if not force:
        for process in processes:
            process.join(timeout=1.0)
    for process in processes:
        if not process.is_alive():
            continue
        process.terminate()
    for process in processes:
        process.join(timeout=1.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=1.0)


def _inspect_document(
    document: StationDesignDocument,
    *,
    case_id: str,
) -> dict[str, Any]:
    compiled = validate_compiled_station_design(
        document,
        generated_contract_scenario(document),
    )
    errors = tuple(issue for issue in compiled.issues if issue.severity == "error")
    facility_ids = Counter(
        str(facility.facility_id) for facility in compiled.facilities
    )
    binding_ids = Counter(
        str(binding.facility_id) for binding in compiled.facility_portal_bindings
    )
    uniquely_bound = sum(
        count == 1 and binding_ids.get(facility_id, 0) == 1
        for facility_id, count in facility_ids.items()
    )
    rate = uniquely_bound / len(compiled.facilities) if compiled.facilities else 0.0
    return {
        "status": "ok" if not errors and rate == 1.0 else "review",
        "case_id": case_id,
        "facility_count": len(compiled.facilities),
        "binding_count": len(compiled.facility_portal_bindings),
        "facility_binding_rate": round(rate, 6),
        "error_codes": tuple(issue.code for issue in errors),
        "error": None if not errors else "; ".join(issue.message for issue in errors),
    }


def _inspect_recipe(recipe) -> dict[str, Any]:
    try:
        document = generate_layout(recipe)
        record = _inspect_document(document, case_id=recipe.recipe_id)
        record.update(
            {
                "recipe_id": recipe.recipe_id,
                "seed": recipe.seed,
                "archetype": recipe.archetype,
                "topology_footprint": recipe.topology_footprint,
                "requested_vertical_topology": (
                    recipe.requested_vertical_topology or recipe.vertical_topology
                ),
                "effective_vertical_topology": recipe.vertical_topology,
                "fare_topology": recipe.fare_topology,
                "geometry_fingerprint": _geometry_fingerprint(document),
            }
        )
        return record
    except Exception as exc:
        return _failed_recipe_record(recipe, exc)


def _failed_recipe_record(recipe, exc: Exception) -> dict[str, Any]:
    return {
        "status": "review",
        "case_id": recipe.recipe_id,
        "recipe_id": recipe.recipe_id,
        "seed": recipe.seed,
        "error_codes": (type(exc).__name__,),
        "error": f"{type(exc).__name__}: {exc}",
    }


def _geometry_fingerprint(document: StationDesignDocument) -> str:
    """Hash physical layout semantics while ignoring recipe/document identity.

    Top-level IDs, labels, metadata, and generated recipe provenance must not
    make a cloned station appear geometrically distinct. Connections are
    deliberately excluded: this gate measures physical geometry and queue
    materialisation; graph correctness is checked by compilation.
    """

    payload = document.as_dict()
    levels = tuple(payload.get("levels", ()))
    level_order = {
        str(level.get("id")): int(level.get("order", index))
        for index, level in enumerate(levels)
    }
    elements = tuple(payload.get("elements", ()))
    element_by_id = {str(element.get("id")): element for element in elements}

    def level_ref(value: object) -> object:
        return level_order.get(str(value), value)

    canonical_levels = _sort_structures(
        {
            "elevation_m": level.get("elevation_m"),
            "floor_to_floor_height_m": level.get("floor_to_floor_height_m"),
            "order": level.get("order"),
            "footprint": level.get("footprint"),
        }
        for level in levels
    )
    canonical_elements = _sort_structures(
        {
            "kind": element.get("kind"),
            "role": element.get("role"),
            "level": level_ref(element.get("level_id")),
            "geometry": element.get("geometry"),
            "connects_levels": sorted(
                level_ref(level_id) for level_id in element.get("connects_levels", ())
            ),
            "capacity": element.get("capacity"),
            "gate_direction": element.get("gate_direction"),
            "direction": element.get("direction"),
            "line_id": element.get("line_id"),
            "ports": _sort_structures(
                {
                    "kind": port.get("kind"),
                    "direction": port.get("direction"),
                    "level": level_ref(port.get("level_id")),
                    "position_m": port.get("position_m"),
                }
                for port in element.get("ports", ())
            ),
        }
        for element in elements
    )
    canonical_queues = _sort_structures(
        {
            "owner": _queue_owner_geometry(
                element_by_id.get(str(queue.get("owner_element_id"))),
                level_ref,
            ),
            "kind": queue.get("kind"),
            "level": level_ref(queue.get("level_id")),
            "geometry": queue.get("geometry"),
            "service_point_m": queue.get("service_point_m"),
            "capacity": queue.get("capacity"),
            "spacing_m": queue.get("spacing_m"),
            "direction_deg": queue.get("direction_deg"),
            "service_direction": queue.get("service_direction"),
        }
        for queue in payload.get("queues", ())
    )
    canonical = {
        "constraints": payload.get("constraints"),
        "levels": canonical_levels,
        "elements": canonical_elements,
        "queues": canonical_queues,
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _queue_owner_geometry(element: Any, level_ref) -> dict[str, Any] | None:
    if element is None:
        return None
    return {
        "kind": element.get("kind"),
        "role": element.get("role"),
        "level": level_ref(element.get("level_id")),
        "geometry": element.get("geometry"),
    }


def _sort_structures(items) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: json.dumps(
            item,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _expected_requested_cells() -> Counter[tuple[str, str, str, str]]:
    return Counter(
        {
            (archetype, footprint, topology, fare): len(GEOMETRY_MATRIX_SEEDS)
            for archetype in ARCHETYPES
            for footprint in TOPOLOGY_FOOTPRINTS
            for topology in VERTICAL_TOPOLOGIES
            for fare in FARE_TOPOLOGIES
        }
    )


def _expected_effective_seeded_cells() -> Counter[tuple[str, str, str, str, int]]:
    expected: Counter[tuple[str, str, str, str, int]] = Counter()
    for archetype in ARCHETYPES:
        level_count = {
            "single_terminal": 1,
            "two_level_island": 2,
            "two_level_multi_access": 2,
            "three_level_transfer": 3,
        }[archetype]
        for footprint in TOPOLOGY_FOOTPRINTS:
            for requested in VERTICAL_TOPOLOGIES:
                effective = requested
                if level_count == 1:
                    effective = "FULL"
                elif requested == "CHAIN" and level_count != 3:
                    effective = "FULL"
                for fare in FARE_TOPOLOGIES:
                    for seed in GEOMETRY_MATRIX_SEEDS:
                        expected[
                            (archetype, footprint, effective, fare, seed)
                        ] += 1
    return expected


__all__ = ["run_generated_geometry_acceptance"]
