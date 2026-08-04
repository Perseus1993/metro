from __future__ import annotations

import gc
import hashlib
import os
import platform
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from metro_station.application.semantic_fingerprints import semantic_fingerprint
from metro_station_testkit.layout_corpus import corpus_coverage
from metro_station_testkit.layout_recipe import ScenarioCorpus

from .generated_layout_acceptance import inspect_generated_recipe


GENERATED_SCALE_SHARD_SCHEMA_VERSION = "generated_scale_shard.v1"
GENERATED_SCALE_MERGED_SCHEMA_VERSION = "generated_scale_merged.v1"
GENERATED_SIMULATION_MERGED_SCHEMA_VERSION = "generated_simulation_merged.v1"
RecordCallback = Callable[[dict[str, Any], dict[str, Any]], None]


def stable_recipe_shard(recipe_id: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(recipe_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def run_generated_scale_shard(
    corpus: ScenarioCorpus,
    *,
    shard_index: int = 0,
    shard_count: int = 1,
    resume_payload: Mapping[str, Any] | None = None,
    on_record: RecordCallback | None = None,
    max_new_cases: int | None = None,
    checkpoint_interval: int = 1_000,
    workspace: Path | None = None,
) -> dict[str, Any]:
    _validate_shard(shard_index, shard_count)
    if max_new_cases is not None and max_new_cases < 0:
        raise ValueError("max_new_cases cannot be negative")
    if checkpoint_interval <= 0:
        raise ValueError("checkpoint_interval must be positive")
    config = _run_config(corpus, shard_index, shard_count)
    (
        resumed_records,
        resumed_attempts,
        parent_run_id,
        resumed_metrics,
        resumed_checkpoints,
    ) = _resume_state(
        resume_payload,
        config,
    )
    selected = tuple(
        recipe
        for recipe in corpus.recipes
        if stable_recipe_shard(recipe.recipe_id, shard_count) == shard_index
    )
    selected_ids = tuple(recipe.recipe_id for recipe in selected)
    records = dict(resumed_records)
    attempts = list(resumed_attempts)
    checkpoints: list[dict[str, Any]] = list(resumed_checkpoints)
    resumed_wall_seconds = float(resumed_metrics.get("wall_seconds", 0.0))
    started = time.perf_counter()
    tracing_was_active = tracemalloc.is_tracing()
    if not tracing_was_active:
        tracemalloc.start()
    else:
        tracemalloc.reset_peak()
    new_case_count = 0
    try:
        for recipe in selected:
            if recipe.recipe_id in records:
                continue
            if max_new_cases is not None and new_case_count >= max_new_cases:
                break
            case_started = time.perf_counter()
            record = inspect_generated_recipe(recipe).as_dict()
            wall_seconds = time.perf_counter() - case_started
            attempt = {
                "recipe_id": recipe.recipe_id,
                "attempt": 1,
                "status": record["status"],
                "wall_seconds": round(wall_seconds, 6),
                "error": record.get("error"),
            }
            records[recipe.recipe_id] = record
            attempts.append(attempt)
            new_case_count += 1
            progress = {
                "completed_cases": len(records),
                "selected_cases": len(selected),
                "new_cases": new_case_count,
            }
            if on_record is not None:
                on_record(record, {**config, **progress, "attempt": attempt})
            if len(records) % checkpoint_interval == 0:
                checkpoints.append(
                    _memory_checkpoint(len(records), started, resumed_wall_seconds)
                )
        checkpoints.append(_memory_checkpoint(len(records), started, resumed_wall_seconds))
        current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        if not tracing_was_active:
            tracemalloc.stop()

    ordered_records = tuple(records[recipe_id] for recipe_id in selected_ids if recipe_id in records)
    missing_ids = tuple(recipe_id for recipe_id in selected_ids if recipe_id not in records)
    failed_ids = tuple(
        str(record["recipe_id"])
        for record in ordered_records
        if record.get("status") != "ok"
    )
    checks = {
        "records_belong_to_shard": all(
            stable_recipe_shard(str(record["recipe_id"]), shard_count) == shard_index
            for record in ordered_records
        ),
        "completed_recipe_ids_unique": len(ordered_records)
        == len({str(record["recipe_id"]) for record in ordered_records}),
        "completed_records_preserved_on_resume": all(
            records[recipe_id] == record for recipe_id, record in resumed_records.items()
        ),
        "all_selected_cases_completed": not missing_ids,
        "all_completed_cases_pass": all(
            record.get("status") == "ok" for record in ordered_records
        )
        and (bool(ordered_records) or not selected),
    }
    current_elapsed = time.perf_counter() - started
    elapsed = resumed_wall_seconds + current_elapsed
    peak_traced_mb = max(
        float(resumed_metrics.get("peak_traced_memory_mb", 0.0)),
        peak_bytes / 1024 / 1024,
    )
    current_traced_mb = (
        current_bytes / 1024 / 1024
        if new_case_count
        else float(resumed_metrics.get("current_traced_memory_mb", 0.0))
    )
    return {
        "schema_version": GENERATED_SCALE_SHARD_SCHEMA_VERSION,
        "status": "ok" if all(checks.values()) else "review",
        "run_id": _run_id(config),
        "parent_run_id": parent_run_id,
        "config": config,
        "environment": scale_environment_manifest(workspace or Path.cwd()),
        "selected_recipe_ids": selected_ids,
        "records": ordered_records,
        "attempts": tuple(attempts),
        "failed_recipe_ids": failed_ids,
        "missing_recipe_ids": missing_ids,
        "checkpoints": tuple(checkpoints),
        "metrics": {
            "selected_cases": len(selected),
            "completed_cases": len(ordered_records),
            "resumed_cases": len(resumed_records),
            "new_cases": new_case_count,
            "wall_seconds": round(elapsed, 6),
            "throughput_cases_per_second": round(len(ordered_records) / max(elapsed, 1e-9), 6),
            "current_traced_memory_mb": round(current_traced_mb, 6),
            "peak_traced_memory_mb": round(peak_traced_mb, 6),
            "final_rss_mb": round(_process_rss_mb(), 6),
        },
        "checks": checks,
        "canonical_summary": _canonical_shard_summary(config, ordered_records),
    }


def merge_generated_scale_shards(
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not payloads:
        raise ValueError("at least one generated scale shard is required")
    if any(payload.get("schema_version") != GENERATED_SCALE_SHARD_SCHEMA_VERSION for payload in payloads):
        raise ValueError("all inputs must be generated_scale_shard.v1")
    configs = [dict(payload["config"]) for payload in payloads]
    _validate_compatible_configs(configs)
    shard_count = int(configs[0]["shard_count"])
    shard_indices = tuple(int(config["shard_index"]) for config in configs)
    if len(set(shard_indices)) != len(shard_indices):
        raise ValueError("generated scale shards contain duplicate shard indices")
    if set(shard_indices) != set(range(shard_count)):
        raise ValueError("generated scale shard set is incomplete")

    records = [dict(record) for payload in payloads for record in payload.get("records", ())]
    recipe_ids = [str(record["recipe_id"]) for record in records]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("generated scale shards contain duplicate recipe records")
    expected_ids = tuple(str(item) for item in configs[0]["corpus_recipe_ids"])
    record_by_id = {str(record["recipe_id"]): record for record in records}
    ordered_records = tuple(record_by_id[item] for item in expected_ids if item in record_by_id)
    missing_ids = tuple(item for item in expected_ids if item not in record_by_id)
    misplaced_ids = tuple(
        recipe_id
        for payload in payloads
        for recipe_id in (
            str(record["recipe_id"])
            for record in payload.get("records", ())
            if stable_recipe_shard(
                str(record["recipe_id"]),
                int(payload["config"]["shard_count"]),
            )
            != int(payload["config"]["shard_index"])
        )
    )
    failed_ids = tuple(
        str(record["recipe_id"])
        for record in ordered_records
        if record.get("status") != "ok"
    )
    checks = {
        "all_shards_present": set(shard_indices) == set(range(shard_count)),
        "no_duplicate_cases": len(recipe_ids) == len(set(recipe_ids)),
        "no_missing_cases": not missing_ids,
        "all_records_in_declared_shard": not misplaced_ids,
        "all_cases_pass": bool(ordered_records) and not failed_ids,
        "failure_evidence_is_unique": len(failed_ids) == len(set(failed_ids)),
    }
    canonical_summary = _canonical_merged_summary(configs[0], ordered_records)
    return {
        "schema_version": GENERATED_SCALE_MERGED_SCHEMA_VERSION,
        "status": "ok" if all(checks.values()) else "review",
        "corpus_id": configs[0]["corpus_id"],
        "corpus_fingerprint": configs[0]["corpus_fingerprint"],
        "generator_version": configs[0]["generator_version"],
        "shard_count": shard_count,
        "shard_indices": tuple(sorted(shard_indices)),
        "records": ordered_records,
        "failed_recipe_ids": failed_ids,
        "missing_recipe_ids": missing_ids,
        "misplaced_recipe_ids": misplaced_ids,
        "coverage": configs[0]["coverage"],
        "canonical_summary": canonical_summary,
        "canonical_fingerprint": semantic_fingerprint(canonical_summary),
        "checks": checks,
    }


def merge_generated_simulation_shards(
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not payloads:
        raise ValueError("at least one generated simulation shard is required")
    fields = (
        "tier",
        "corpus_id",
        "seeds",
        "include_operations",
        "shard_count",
        "shard_algorithm",
    )
    reference = payloads[0]
    for payload in payloads[1:]:
        if any(payload.get(field) != reference.get(field) for field in fields):
            raise ValueError("incompatible generated simulation shards")
        if tuple(payload.get("global_sampled_recipe_ids", ())) != tuple(
            reference.get("global_sampled_recipe_ids", ())
        ):
            raise ValueError("generated simulation sampling fingerprints differ")
        if tuple(payload.get("global_sampled_case_ids", ())) != tuple(
            reference.get("global_sampled_case_ids", ())
        ):
            raise ValueError("generated simulation case fingerprints differ")
    shard_count = int(reference.get("shard_count", 1))
    shard_indices = tuple(int(payload.get("shard_index", 0)) for payload in payloads)
    if set(shard_indices) != set(range(shard_count)) or len(shard_indices) != shard_count:
        raise ValueError("generated simulation shard set is incomplete or duplicated")
    expected_recipe_ids = tuple(
        str(item) for item in reference.get("global_sampled_recipe_ids", ())
    )
    expected_case_ids = tuple(
        str(item) for item in reference.get("global_sampled_case_ids", ())
    )
    if expected_case_ids:
        keyed_records: list[tuple[str, dict[str, Any]]] = []
        for payload in payloads:
            case_ids = tuple(str(item) for item in payload.get("sampled_case_ids", ()))
            shard_records = tuple(dict(item) for item in payload.get("records", ()))
            if len(case_ids) != len(shard_records):
                raise ValueError("generated simulation case ids do not match records")
            keyed_records.extend(zip(case_ids, shard_records, strict=True))
        sample_ids = [case_id for case_id, _record in keyed_records]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("generated simulation shards contain duplicate cases")
        record_by_id = dict(keyed_records)
        ordered_pairs = tuple(
            (case_id, record_by_id[case_id])
            for case_id in expected_case_ids
            if case_id in record_by_id
        )
        missing = tuple(
            case_id for case_id in expected_case_ids if case_id not in record_by_id
        )
        failed = tuple(
            case_id
            for case_id, record in ordered_pairs
            if record.get("status") != "ok"
        )
        ordered = tuple(record for _case_id, record in ordered_pairs)
        canonical_records = tuple(
            {"case_id": case_id, **_canonical_simulation_record(record)}
            for case_id, record in ordered_pairs
        )
        sample_identity = expected_case_ids
    else:
        records = [
            dict(record)
            for payload in payloads
            for record in payload.get("records", ())
        ]
        recipe_ids = [str(record["recipe_id"]) for record in records]
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("generated simulation shards contain duplicate records")
        record_by_id = {str(record["recipe_id"]): record for record in records}
        ordered = tuple(
            record_by_id[item] for item in expected_recipe_ids if item in record_by_id
        )
        missing = tuple(
            item for item in expected_recipe_ids if item not in record_by_id
        )
        failed = tuple(
            str(record["recipe_id"])
            for record in ordered
            if record.get("status") != "ok"
        )
        canonical_records = tuple(
            _canonical_simulation_record(record) for record in ordered
        )
        sample_identity = tuple(str(record["recipe_id"]) for record in records)
    trajectory_statuses = {
        str(record.get("trajectory_scientific_status")) for record in ordered
    }
    trajectory_scientific_status = (
        "pass"
        if trajectory_statuses == {"pass"}
        else "not_applicable"
        if trajectory_statuses == {"not_applicable"}
        else "fail"
    )
    checks = {
        "all_shards_present": set(shard_indices) == set(range(shard_count)),
        "no_duplicate_samples": len(sample_identity) == len(set(sample_identity)),
        "no_missing_samples": not missing,
        "all_simulations_pass": bool(ordered) and not failed,
        "all_seed_evidence_present": bool(tuple(reference.get("seeds", ()))),
        "trajectory_status_explicit": bool(ordered)
        and trajectory_statuses <= {"pass", "fail", "not_applicable"},
    }
    canonical = {
        "tier": reference.get("tier"),
        "corpus_id": reference.get("corpus_id"),
        "seeds": tuple(reference.get("seeds", ())),
        "include_operations": reference.get("include_operations"),
        "sampled_recipe_ids": expected_recipe_ids,
        "sampled_case_ids": expected_case_ids,
        "records": canonical_records,
    }
    return {
        "schema_version": GENERATED_SIMULATION_MERGED_SCHEMA_VERSION,
        "status": "ok" if all(checks.values()) else "review",
        "trajectory_scientific_status": trajectory_scientific_status,
        **canonical,
        "failed_recipe_ids": tuple(
            sorted(
                {
                    str(record.get("recipe_id"))
                    for record in ordered
                    if record.get("status") != "ok"
                }
            )
        ),
        "missing_recipe_ids": (
            () if expected_case_ids else missing
        ),
        "failed_case_ids": failed if expected_case_ids else (),
        "missing_case_ids": missing if expected_case_ids else (),
        "shard_count": shard_count,
        "shard_algorithm": reference.get("shard_algorithm"),
        "canonical_fingerprint": semantic_fingerprint(canonical),
        "checks": checks,
    }
def scale_environment_manifest(workspace: Path) -> dict[str, Any]:
    lock_path = workspace / "uv.lock"
    git_commit = _command_output(("git", "rev-parse", "HEAD"), workspace)
    dirty_output = _command_output(("git", "status", "--porcelain"), workspace)
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "processor": platform.processor(),
        "git_commit": git_commit,
        "git_dirty": bool(dirty_output),
        "dependency_lock_sha256": (
            hashlib.sha256(lock_path.read_bytes()).hexdigest() if lock_path.exists() else None
        ),
    }


def _run_config(corpus: ScenarioCorpus, shard_index: int, shard_count: int) -> dict[str, Any]:
    return {
        "corpus_id": corpus.corpus_id,
        "corpus_fingerprint": corpus.semantic_fingerprint,
        "generator_version": corpus.generator_version,
        "corpus_size": len(corpus.recipes),
        "corpus_recipe_ids": tuple(recipe.recipe_id for recipe in corpus.recipes),
        "coverage": corpus_coverage(corpus),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "shard_algorithm": "sha256(recipe_id)[0:8] mod shard_count",
    }


def _resume_state(
    payload: Mapping[str, Any] | None,
    config: Mapping[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    tuple[dict[str, Any], ...],
    str | None,
    dict[str, Any],
    tuple[dict[str, Any], ...],
]:
    if payload is None:
        return {}, (), None, {}, ()
    if payload.get("schema_version") != GENERATED_SCALE_SHARD_SCHEMA_VERSION:
        raise ValueError("resume payload must be generated_scale_shard.v1")
    previous = dict(payload.get("config", {}))
    for field in (
        "corpus_id",
        "corpus_fingerprint",
        "generator_version",
        "corpus_size",
        "shard_index",
        "shard_count",
        "shard_algorithm",
    ):
        if previous.get(field) != config.get(field):
            raise ValueError(f"resume configuration mismatch: {field}")
    records = {
        str(record["recipe_id"]): dict(record) for record in payload.get("records", ())
    }
    if len(records) != len(tuple(payload.get("records", ()))):
        raise ValueError("resume payload contains duplicate recipe records")
    selected_ids = {
        recipe_id
        for recipe_id in config["corpus_recipe_ids"]
        if stable_recipe_shard(str(recipe_id), int(config["shard_count"]))
        == int(config["shard_index"])
    }
    if not set(records).issubset(selected_ids):
        raise ValueError("resume payload contains a recipe outside the declared shard")
    return (
        records,
        tuple(dict(item) for item in payload.get("attempts", ())),
        str(payload.get("run_id")),
        dict(payload.get("metrics", {})),
        tuple(dict(item) for item in payload.get("checkpoints", ())),
    )


def _validate_shard(shard_index: int, shard_count: int) -> None:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must satisfy 0 <= shard_index < shard_count")


def _validate_compatible_configs(configs: list[dict[str, Any]]) -> None:
    reference = configs[0]
    for config in configs[1:]:
        for field in (
            "corpus_id",
            "corpus_fingerprint",
            "generator_version",
            "corpus_size",
            "corpus_recipe_ids",
            "shard_count",
            "shard_algorithm",
        ):
            if config.get(field) != reference.get(field):
                raise ValueError(f"incompatible generated scale shards: {field}")


def _canonical_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "recipe_id": record.get("recipe_id"),
        "recipe_fingerprint": record.get("recipe_fingerprint"),
        "design_fingerprint": record.get("design_fingerprint"),
        "status": record.get("status"),
        "checks": dict(record.get("checks", {})),
        "error": record.get("error"),
    }


def _canonical_simulation_record(record: Mapping[str, Any]) -> dict[str, Any]:
    journeys = record.get("journeys") or {}
    operations = record.get("operations") or {}
    return {
        "recipe_id": record.get("recipe_id"),
        "operation_profile": record.get("operation_profile"),
        "operation_scenario_id": record.get("operation_scenario_id"),
        "status": record.get("status"),
        "trajectory_scientific_status": record.get("trajectory_scientific_status"),
        "determinism_fingerprint": record.get("determinism_fingerprint"),
        "journeys_status": journeys.get("status") if isinstance(journeys, Mapping) else None,
        "operations_status": (
            operations.get("status") if isinstance(operations, Mapping) else None
        ),
        "checks": dict(record.get("checks", {})),
        "error": record.get("error"),
    }


def _canonical_shard_summary(
    config: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "corpus_fingerprint": config["corpus_fingerprint"],
        "shard_index": config["shard_index"],
        "shard_count": config["shard_count"],
        "records": [_canonical_record(record) for record in records],
    }


def _canonical_merged_summary(
    config: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "corpus_fingerprint": config["corpus_fingerprint"],
        "generator_version": config["generator_version"],
        "coverage": config["coverage"],
        "records": [_canonical_record(record) for record in records],
    }


def _memory_checkpoint(
    completed_cases: int,
    started: float,
    previous_wall_seconds: float = 0.0,
) -> dict[str, Any]:
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    wall_seconds = previous_wall_seconds + time.perf_counter() - started
    return {
        "completed_cases": completed_cases,
        "wall_seconds": round(wall_seconds, 6),
        "throughput_cases_per_second": round(completed_cases / max(wall_seconds, 1e-9), 6),
        "traced_current_mb": round(current / 1024 / 1024, 6),
        "traced_peak_mb": round(peak / 1024 / 1024, 6),
        "rss_mb": round(_process_rss_mb(), 6),
    }


def _process_rss_mb() -> float:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_process_memory_info = psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCounters),
                wintypes.DWORD,
            )
            get_process_memory_info.restype = wintypes.BOOL
            handle = kernel32.GetCurrentProcess()
            ok = get_process_memory_info(
                handle,
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                return counters.WorkingSetSize / 1024 / 1024
        except Exception:
            pass
    try:
        statm = Path("/proc/self/statm").read_text(encoding="utf-8").split()
        sysconf = getattr(os, "sysconf")
        return int(statm[1]) * int(sysconf("SC_PAGE_SIZE")) / 1024 / 1024
    except Exception:
        return 0.0


def _run_id(config: Mapping[str, Any]) -> str:
    return (
        f"{config['corpus_id']}-shard-{int(config['shard_index']):03d}"
        f"-of-{int(config['shard_count']):03d}"
    )


def _command_output(command: tuple[str, ...], workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()
