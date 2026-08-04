from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from metro_station.adapters.simulation.runtime.audit import GLOBAL_AUDIT
from metro_station.application.simulation import run_simulation
from metro_station.domain.time_boundaries import (
    first_step_not_before,
    positive_steps_to_cover,
)

from metro_alignment.analysis_runtime import analysis_runtime_fingerprint
from metro_alignment.artifact_io import write_json_atomic
from metro_alignment.canonical import CANONICAL_SCHEMA_VERSION, write_canonical
from metro_alignment.metrics.fundamental import METRIC_SCHEMA_VERSION
from metro_alignment.metro_contract import (
    SCENE_CONFIG_SCHEMA_VERSION,
    scene_config_payload,
    scene_config_sha256,
    verify_scene_config_record,
)
from metro_alignment.metro_executor import (
    AlignmentMesaSimulationExecutor,
    AlignmentSourceGeometryConflict,
    alignment_source_geometry_preflight,
)
from metro_alignment.metro_runtime import metro_source_fingerprint
from metro_alignment.metro_scene import build_metro_request, build_metro_scenario
from metro_alignment.metro_trace import movement_trace_to_canonical
from metro_alignment.scenes import (
    SCENE_FACTORIES,
    SceneConfig,
    build_scene_config,
    list_scene_configs,
)
from metro_alignment.simulation_evidence import (
    compute_simulated_metrics,
    simulated_trajectory_summary,
)

SIMULATED_ARTIFACT_SCHEMA_VERSION = "alignment_simulation_metrics.v5"


@dataclass(frozen=True)
class RunAlignmentResult:
    canonical_path: Path
    metrics_path: Path
    trace_path: Path
    scene_id: str
    trace_points: int


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path, *, manifest_path: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(manifest_path.parent.resolve()).as_posix(),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _runtime_fingerprints_match(
    expected_metro: dict[str, Any], expected_analysis: dict[str, Any]
) -> bool:
    return (
        metro_source_fingerprint() == expected_metro
        and analysis_runtime_fingerprint() == expected_analysis
    )


def _require_admission_acceptance(
    final_metrics: dict[str, Any],
    *,
    expected_entry_persons: int,
    expected_exit_persons: int,
    expected_departed_trains: int,
) -> None:
    required_equal = {
        "spawned_entry_persons": expected_entry_persons,
        "spawned_exit_persons": expected_exit_persons,
        "alignment_scheduled_entry_persons": expected_entry_persons,
        "pending_alighting_persons": 0,
        "alignment_pending_source_groups": 0,
        "alignment_pending_source_persons": 0,
        "alignment_pending_entry_groups": 0,
        "alignment_pending_entry_persons": 0,
        "alignment_entry_dropped_persons": 0,
        "alignment_source_dropped_persons": 0,
        "jupedsim_missing_agents": 0,
        "jupedsim_degraded_holds": 0,
        "alignment_active_boardings": 0,
        "alignment_reserved_boarding_persons": 0,
        "departed_trains": expected_departed_trains,
    }
    failures = [
        f"{key}={final_metrics.get(key)!r}, expected {expected!r}"
        for key, expected in required_equal.items()
        if final_metrics.get(key) != expected
    ]
    for key in (
        "alignment_entry_demand_conserved",
        "alignment_source_demand_conserved",
    ):
        if final_metrics.get(key) is not True:
            failures.append(f"{key}={final_metrics.get(key)!r}, expected True")
    if final_metrics.get("alignment_requested_due_source_persons") != final_metrics.get(
        "alignment_scheduled_source_persons"
    ):
        failures.append(
            "alignment_requested_due_source_persons="
            f"{final_metrics.get('alignment_requested_due_source_persons')!r}, expected "
            "alignment_scheduled_source_persons="
            f"{final_metrics.get('alignment_scheduled_source_persons')!r}"
        )
    if failures:
        raise RuntimeError(
            "alignment admission acceptance failed; refusing formal evidence: "
            + "; ".join(failures)
        )


def _expected_departed_train_runs(scenario) -> int:
    first_arrival = first_step_not_before(
        scenario.initial_train_offset_seconds,
        scenario.tick_seconds,
    )
    headway = positive_steps_to_cover(
        scenario.train_headway_seconds,
        scenario.tick_seconds,
    )
    dwell = positive_steps_to_cover(
        scenario.train_dwell_seconds,
        scenario.tick_seconds,
    )
    count = 0
    arrival = first_arrival
    while arrival <= scenario.demand_steps and arrival + dwell <= scenario.horizon_steps:
        count += 1
        arrival += headway
    return count


def _promote_content(staged: Path, final: Path) -> bool:
    """Promote immutable content, returning whether this call created it."""

    if final.exists():
        if _sha256_file(final) != _sha256_file(staged):
            raise RuntimeError(f"content-addressed target disagrees with staged bytes: {final}")
        staged.unlink()
        return False
    os.replace(staged, final)
    return True


def _publish_staged_bundle(
    *,
    staged_canonical: Path,
    staged_trace: Path,
    canonical_path: Path,
    trace_path: Path,
    manifest_path: Path,
    payload: dict[str, Any],
    expected_metro_fingerprint: dict[str, Any],
    expected_analysis_fingerprint: dict[str, Any],
) -> None:
    """Publish immutable artifacts and atomically switch the manifest pointer.

    A failed promotion or a source change leaves the previous formal manifest and
    every artifact it references untouched. Newly created unreferenced content is
    removed on the handled failure path.
    """

    token = uuid4().hex
    staged_manifest = manifest_path.with_name(f".{manifest_path.name}.{token}.staging.json")
    manifest_backup = manifest_path.with_name(f".{manifest_path.name}.{token}.previous.json")
    created: list[Path] = []
    published_manifest = False
    had_manifest = manifest_path.exists()
    preserve_recovery_bundle = False
    try:
        if not _runtime_fingerprints_match(
            expected_metro_fingerprint, expected_analysis_fingerprint
        ):
            raise RuntimeError("runtime source changed before evidence promotion")
        if _promote_content(staged_canonical, canonical_path):
            created.append(canonical_path)
        if _promote_content(staged_trace, trace_path):
            created.append(trace_path)
        payload["artifacts"] = {
            "canonical": _artifact_record(canonical_path, manifest_path=manifest_path),
            "movement_trace": _artifact_record(trace_path, manifest_path=manifest_path),
        }
        _write_json(staged_manifest, payload)
        if not _runtime_fingerprints_match(
            expected_metro_fingerprint, expected_analysis_fingerprint
        ):
            raise RuntimeError("runtime source changed before manifest publication")
        if had_manifest:
            shutil.copy2(manifest_path, manifest_backup)
        os.replace(staged_manifest, manifest_path)
        published_manifest = True
        if not _runtime_fingerprints_match(
            expected_metro_fingerprint, expected_analysis_fingerprint
        ):
            raise RuntimeError("runtime source changed during evidence publication")
        if manifest_backup.exists():
            manifest_backup.unlink()
    except BaseException:
        if published_manifest:
            try:
                if had_manifest and manifest_backup.exists():
                    os.replace(manifest_backup, manifest_path)
                elif manifest_path.exists():
                    manifest_path.unlink()
            except OSError as rollback_error:
                preserve_recovery_bundle = True
                raise RuntimeError(
                    "evidence publication failed and automatic manifest rollback also failed; "
                    f"recovery manifest retained at {manifest_backup}"
                ) from rollback_error
        if preserve_recovery_bundle:
            raise
        for path in reversed(created):
            if path.exists():
                path.unlink()
        raise
    finally:
        cleanup = [staged_canonical, staged_trace, staged_manifest]
        if not preserve_recovery_bundle:
            cleanup.append(manifest_backup)
        for path in cleanup:
            if path.exists():
                path.unlink()


def _run_simulation(
    config: SceneConfig,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    # Preserve structured audit events in Metro's runtime state without formatting
    # and printing thousands of diagnostic lines during long evidence runs.
    GLOBAL_AUDIT.print_events = False
    runtime_fingerprint = metro_source_fingerprint()
    analysis_fingerprint = analysis_runtime_fingerprint()
    request, design_sha256 = build_metro_request(config)
    execution = run_simulation(
        request,
        AlignmentMesaSimulationExecutor(),
    )
    frames = execution.frames
    trace = execution.runtime.movement_backend.movement_trace()
    final_metrics = dict(frames[-1].get("metrics", {})) if frames else {}
    final_metrics.update(execution.runtime.alignment_source_admission_metrics())
    _require_admission_acceptance(
        final_metrics,
        expected_entry_persons=int(
            execution.runtime.scenario.entry_groups
            * execution.runtime.scenario.group_size
        ),
        expected_exit_persons=int(
            execution.runtime.scenario.exit_groups
            * execution.runtime.scenario.group_size
        ),
        expected_departed_trains=_expected_departed_train_runs(execution.runtime.scenario),
    )
    if metro_source_fingerprint() != runtime_fingerprint:
        raise RuntimeError("Metro source changed during the simulation; refusing stale evidence")
    if analysis_runtime_fingerprint() != analysis_fingerprint:
        raise RuntimeError("alignment analysis source changed during the simulation")
    return trace, final_metrics, design_sha256, runtime_fingerprint, analysis_fingerprint


def _load_verified_trace_replay(
    *, output: Path, config: SceneConfig
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    """Reuse an already generated authoritative trace after analysis-code changes."""

    scenario, design_sha256 = build_metro_scenario(config)
    preflight = alignment_source_geometry_preflight(scenario)
    if preflight["status"] != "pass":
        raise AlignmentSourceGeometryConflict(preflight)

    manifest_path = output.parent / f"{config.scene_id}_simulated.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"cannot replay without existing manifest: {manifest_path}")
    existing = json.loads(manifest_path.read_bytes())
    analysis_fingerprint = analysis_runtime_fingerprint()
    if existing.get("schema_version") != SIMULATED_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("trace replay requires a current v5 simulation manifest")
    if (
        existing.get("scene_id") != config.scene_id
        or existing.get("simulation_seed") != config.seed
    ):
        raise ValueError("trace replay scene/seed does not match the requested configuration")
    runtime_fingerprint = metro_source_fingerprint()
    if existing.get("metro_runtime_fingerprint") != runtime_fingerprint:
        raise ValueError("trace replay Metro source fingerprint does not match the current runtime")
    verify_scene_config_record(existing, config)

    record = existing.get("artifacts", {}).get("movement_trace", {})
    relative = Path(str(record.get("path", "")))
    trace_path = (manifest_path.parent / relative).resolve()
    if relative.is_absolute() or not trace_path.is_relative_to(manifest_path.parent.resolve()):
        raise ValueError("trace replay manifest has a non-portable trace path")
    if not trace_path.is_file():
        raise ValueError("trace replay artifact is missing or not a regular file")
    trace_bytes = trace_path.read_bytes()
    if len(trace_bytes) != int(record.get("size_bytes", -1)) or hashlib.sha256(
        trace_bytes
    ).hexdigest() != record.get("sha256"):
        raise ValueError("trace replay artifact size/hash verification failed")

    if design_sha256 != existing.get("design_sha256"):
        raise ValueError("trace replay design hash does not match the current compiled design")
    final_metrics = dict(existing.get("final_frame_metrics", {}))
    _require_admission_acceptance(
        final_metrics,
        expected_entry_persons=int(scenario.entry_groups * scenario.group_size),
        expected_exit_persons=int(scenario.exit_groups * scenario.group_size),
        expected_departed_trains=_expected_departed_train_runs(scenario),
    )
    trace = json.loads(trace_bytes)
    return (
        trace,
        final_metrics,
        design_sha256,
        runtime_fingerprint,
        analysis_fingerprint,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)


def _write_source_preflight_blocker(
    *,
    output: Path,
    config: SceneConfig,
    report: dict[str, Any],
) -> Path:
    _, design_sha256 = build_metro_scenario(config)
    path = output.parent / f"{config.scene_id}_source_preflight.json"
    _write_json(
        path,
        {
            "schema_version": "alignment_source_preflight_artifact.v1",
            "scene_id": config.scene_id,
            "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
            "scene_config": scene_config_payload(config),
            "scene_config_sha256": scene_config_sha256(config),
            "design_sha256": design_sha256,
            "metro_runtime_fingerprint": metro_source_fingerprint(),
            "analysis_runtime_fingerprint": analysis_runtime_fingerprint(),
            "runtime_status": "not_started",
            "scientific_status": "model_invalid",
            "blocker": "alighting_source_geometry_conflict",
            "release_eligible": False,
            "preflight": report,
        },
    )
    return path


def _retire_source_preflight_blocker(*, output: Path, config: SceneConfig) -> None:
    """Remove a superseded blocker only after a new bundle is fully published."""

    path = output.parent / f"{config.scene_id}_source_preflight.json"
    if path.exists():
        path.unlink()


def _write_run_outputs(
    *,
    output: Path,
    config: SceneConfig,
    trace: dict[str, Any],
    final_metrics: dict[str, Any],
    design_sha256: str,
    metro_runtime_fingerprint: dict[str, Any],
    analysis_runtime_fingerprint_at_start: dict[str, Any],
) -> RunAlignmentResult:
    conversion = movement_trace_to_canonical(
        trace,
        dataset_id=f"simulation:{config.scene_id}",
        phases=("walking",),
    )
    canonical_df = conversion.trajectory
    metrics_path = output.parent / f"{config.scene_id}_simulated.json"
    metrics = compute_simulated_metrics(conversion, config=config)
    payload = {
        "schema_version": SIMULATED_ARTIFACT_SCHEMA_VERSION,
        "scene_id": config.scene_id,
        "simulation_seed": int(config.seed),
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
        "metric_schema_version": METRIC_SCHEMA_VERSION,
        "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
        "scene_config": scene_config_payload(config),
        "scene_config_sha256": scene_config_sha256(config),
        "design_sha256": design_sha256,
        "metro_runtime_fingerprint": metro_runtime_fingerprint,
        "analysis_runtime_fingerprint": analysis_runtime_fingerprint_at_start,
        "scientific_comparability": {
            "geometry_evidence_status": config.geometry_evidence_status,
            "geometry_evidence": config.geometry_evidence,
            "geometry_evidence_sha256": config.geometry_evidence_sha256,
            "release_eligible": (
                config.geometry_evidence_status == "observed_matched"
                and config.geometry_evidence_sha256 is not None
            ),
        },
        "trace_provenance": conversion.provenance,
        "metrics": metrics,
        "final_frame_metrics": dict(final_metrics),
        "trajectory": simulated_trajectory_summary(conversion),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    staged_canonical = output.with_name(f".{output.name}.{token}.staging.parquet")
    staged_trace = output.with_name(f".{output.stem}.{token}.staging.movement_trace.json")
    try:
        write_canonical(canonical_df, staged_canonical)
        _write_json(staged_trace, trace)
        canonical_sha256 = _sha256_file(staged_canonical)
        trace_sha256 = _sha256_file(staged_trace)
        canonical_path = output.with_name(
            f"{output.stem}.sha256-{canonical_sha256}{output.suffix}"
        )
        trace_path = output.with_name(
            f"{output.stem}.sha256-{trace_sha256}.movement_trace.json"
        )
        _publish_staged_bundle(
            staged_canonical=staged_canonical,
            staged_trace=staged_trace,
            canonical_path=canonical_path,
            trace_path=trace_path,
            manifest_path=metrics_path,
            payload=payload,
            expected_metro_fingerprint=metro_runtime_fingerprint,
            expected_analysis_fingerprint=analysis_runtime_fingerprint_at_start,
        )
        _retire_source_preflight_blocker(output=output, config=config)
    finally:
        for path in (staged_canonical, staged_trace):
            if path.exists():
                path.unlink()
    return RunAlignmentResult(
        canonical_path=canonical_path,
        metrics_path=metrics_path,
        trace_path=trace_path,
        scene_id=config.scene_id,
        trace_points=len(trace.get("points", [])),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an evidence-scoped alignment scene and export canonical trajectory."
    )
    parser.add_argument("--scene-id", choices=sorted(SCENE_FACTORIES))
    parser.add_argument("--output", type=Path, help="output canonical trajectory path")
    parser.add_argument("--seed", type=int, default=None, help="optional seed override")
    parser.add_argument("--minutes", type=int, default=None, help="shorter duration for smoke runs")
    parser.add_argument(
        "--reuse-existing-trace",
        action="store_true",
        help="verify and reprocess an existing authoritative trace without rerunning Metro",
    )
    parser.add_argument("--list-scenes", action="store_true")
    return parser.parse_args()


def _apply_cli_overrides(
    config: SceneConfig,
    *,
    seed: int | None,
    minutes: int | None,
) -> SceneConfig:
    overrides: dict[str, Any] = {}
    if seed is not None:
        overrides["seed"] = int(seed)
    if minutes is not None:
        selected_minutes = int(minutes)
        if not 1 <= selected_minutes <= int(config.minutes):
            raise ValueError(
                "--minutes is a smoke-run upper bound and must be between 1 and "
                f"the registered {config.minutes} minutes"
            )
        overrides["minutes"] = selected_minutes
        overrides["demand_minutes"] = min(
            int(config.demand_minutes),
            selected_minutes,
        )
    return replace(config, **overrides)


def main() -> None:
    args = parse_args()
    if args.list_scenes:
        print(
            json.dumps(
                {
                    scene_id: {
                        "status": config.status,
                        "pending_reason": config.pending_reason,
                    }
                    for scene_id, config in list_scene_configs()
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not args.scene_id or args.output is None:
        raise SystemExit("--scene-id and --output are required unless --list-scenes is used")

    config = build_scene_config(args.scene_id)
    if config.status != "ready":
        raise SystemExit(f"scene {config.scene_id} is pending: {config.pending_reason}")
    try:
        config = _apply_cli_overrides(
            config,
            seed=args.seed,
            minutes=args.minutes,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        if args.reuse_existing_trace:
            (
                trace,
                final_metrics,
                design_sha256,
                runtime_fingerprint,
                analysis_fingerprint,
            ) = _load_verified_trace_replay(output=args.output, config=config)
        else:
            (
                trace,
                final_metrics,
                design_sha256,
                runtime_fingerprint,
                analysis_fingerprint,
            ) = _run_simulation(config)
    except AlignmentSourceGeometryConflict as exc:
        blocker_path = _write_source_preflight_blocker(
            output=args.output,
            config=config,
            report=exc.report,
        )
        print(f"source preflight blocker: {blocker_path}")
        raise
    result = _write_run_outputs(
        output=args.output,
        config=config,
        trace=trace,
        final_metrics=final_metrics,
        design_sha256=design_sha256,
        metro_runtime_fingerprint=runtime_fingerprint,
        analysis_runtime_fingerprint_at_start=analysis_fingerprint,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "scene_id": result.scene_id,
                "canonical": str(result.canonical_path),
                "metrics": str(result.metrics_path),
                "trace": str(result.trace_path),
                "trace_points": result.trace_points,
                "seed": config.seed,
                "design_sha256": design_sha256,
                "mode": "trace_replay" if args.reuse_existing_trace else "simulation",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
