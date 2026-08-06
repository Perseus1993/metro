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
from metro_alignment.formal_ladder import (
    FormalControlExecution,
    execute_final_ladder,
)
from metro_alignment.formal_profiles import (
    FINAL_LADDER_PROFILE_ID,
    MULTI_SEED_NIGHTLY_PROFILE_ID,
    FormalControlSpec,
    final_ladder_profile,
    multi_seed_nightly_profile,
)
from metro_alignment.metrics.fundamental import METRIC_SCHEMA_VERSION
from metro_alignment.metro_contract import (
    SCENE_CONFIG_SCHEMA_VERSION,
    scene_config_payload,
    scene_config_sha256,
    verify_scene_config_record,
)
from metro_alignment.metro_executor import (
    AlignmentAdmissionCapacityConflict,
    AlignmentMesaSimulationExecutor,
    AlignmentSourceGeometryConflict,
    alignment_entry_admission_preflight,
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
from metro_alignment.source_integrity_gate import require_source_integrity_gate

SIMULATED_ARTIFACT_SCHEMA_VERSION = "alignment_simulation_metrics.v5"
SOURCE_PREFLIGHT_ARTIFACT_SCHEMA_VERSION = "alignment_source_preflight_artifact.v2"
ADMISSION_PREFLIGHT_ARTIFACT_SCHEMA_VERSION = "alignment_admission_preflight_artifact.v1"


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
    require_source_integrity_gate(final_metrics)
    required_equal = {
        "alignment_scheduled_entry_persons": expected_entry_persons,
        "alignment_scheduled_exit_persons": expected_exit_persons,
        "pending_alighting_persons": 0,
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
    # Keep transaction filenames independent of the public manifest name.
    # ``write_json_atomic`` adds its own staging suffix; repeating a long
    # manifest name here exceeded legacy Windows MAX_PATH in nested ladder runs.
    staged_manifest = manifest_path.with_name(f".m-{token}.json")
    manifest_backup = manifest_path.with_name(f".b-{token}.json")
    manifest_atomic_stage = staged_manifest.with_name(
        f".{staged_manifest.name}.{'f' * 32}.staging"
    )
    _require_windows_path_budget(
        staged_canonical,
        staged_trace,
        canonical_path,
        trace_path,
        manifest_path,
        staged_manifest,
        manifest_backup,
        manifest_atomic_stage,
    )
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
    *,
    formal_horizon_steps: int | None = None,
    require_final_acceptance: bool = True,
    expected_departed_trains: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    # Preserve structured audit events in Metro's runtime state without formatting
    # and printing thousands of diagnostic lines during long evidence runs.
    GLOBAL_AUDIT.print_events = False
    runtime_fingerprint = metro_source_fingerprint()
    analysis_fingerprint = analysis_runtime_fingerprint()
    request, design_sha256 = build_metro_request(config)
    execution = run_simulation(
        request,
        AlignmentMesaSimulationExecutor(formal_horizon_steps=formal_horizon_steps),
    )
    frames = execution.frames
    trace = execution.runtime.movement_backend.movement_trace()
    final_metrics = dict(frames[-1].get("metrics", {})) if frames else {}
    final_metrics.update(execution.runtime.alignment_source_admission_metrics())
    if require_final_acceptance:
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
            expected_departed_trains=(
                _expected_departed_train_runs(execution.runtime.scenario)
                if expected_departed_trains is None
                else expected_departed_trains
            ),
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
    admission_preflight = alignment_entry_admission_preflight(scenario)
    if admission_preflight["status"] != "pass":
        raise AlignmentAdmissionCapacityConflict(admission_preflight)

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


def _write_source_preflight_artifact(
    *,
    output: Path,
    config: SceneConfig,
    report: dict[str, Any],
) -> Path:
    _, design_sha256 = build_metro_scenario(config)
    path = output.parent / f"{config.scene_id}_source_preflight.json"
    passed = report.get("status") == "pass"
    _write_json(
        path,
        {
            "schema_version": SOURCE_PREFLIGHT_ARTIFACT_SCHEMA_VERSION,
            "scene_id": config.scene_id,
            "scene_class": config.scene_class,
            "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
            "scene_config": scene_config_payload(config),
            "scene_config_sha256": scene_config_sha256(config),
            "design_sha256": design_sha256,
            "metro_runtime_fingerprint": metro_source_fingerprint(),
            "analysis_runtime_fingerprint": analysis_runtime_fingerprint(),
            "runtime_status": "ready" if passed else "not_started",
            "scientific_status": "eligible" if passed else "model_invalid",
            "blocker": None if passed else "alighting_source_geometry_conflict",
            "release_eligible": False,
            "preflight": report,
        },
    )
    return path


def _write_source_preflight_blocker(
    *,
    output: Path,
    config: SceneConfig,
    report: dict[str, Any],
) -> Path:
    if report.get("status") != "fail":
        raise ValueError("source preflight blocker requires a failed report")
    return _write_source_preflight_artifact(output=output, config=config, report=report)


def _write_admission_preflight_artifact(
    *,
    output: Path,
    config: SceneConfig,
    report: dict[str, Any],
) -> Path:
    _, design_sha256 = build_metro_scenario(config)
    path = output.parent / f"{config.scene_id}_admission_preflight.json"
    passed = report.get("status") == "pass"
    _write_json(
        path,
        {
            "schema_version": ADMISSION_PREFLIGHT_ARTIFACT_SCHEMA_VERSION,
            "scene_id": config.scene_id,
            "scene_config_schema_version": SCENE_CONFIG_SCHEMA_VERSION,
            "scene_config": scene_config_payload(config),
            "scene_config_sha256": scene_config_sha256(config),
            "design_sha256": design_sha256,
            "metro_runtime_fingerprint": metro_source_fingerprint(),
            "analysis_runtime_fingerprint": analysis_runtime_fingerprint(),
            "runtime_status": "ready" if passed else "not_started",
            "blocker": None if passed else "admission_capacity_undersized",
            "release_eligible": False,
            "preflight": report,
        },
    )
    return path


def _retire_source_preflight_blocker(*, output: Path, config: SceneConfig) -> None:
    """Remove a superseded blocker only after a new bundle is fully published."""

    path = output.parent / f"{config.scene_id}_source_preflight.json"
    if path.exists() and json.loads(path.read_bytes()).get("preflight", {}).get(
        "status"
    ) == "fail":
        path.unlink()


def _staged_output_paths(output: Path, token: str) -> tuple[Path, Path]:
    # write_json_atomic adds its own UUID suffix. Short basenames keep nested
    # formal-ladder paths below the legacy Windows MAX_PATH boundary.
    return (
        output.with_name(f".canonical-{token}.tmp"),
        output.with_name(f".trace-{token}.tmp"),
    )


def _require_windows_path_budget(
    *paths: Path,
    platform_name: str | None = None,
    max_path_chars: int = 259,
) -> None:
    """Fail before publication when a legacy Windows path cannot be represented."""

    platform = os.name if platform_name is None else platform_name
    if platform != "nt":
        return
    offenders = [
        (path, len(str(path.resolve())))
        for path in paths
        if len(str(path.resolve())) > max_path_chars
    ]
    if offenders:
        details = "; ".join(f"{length} chars: {path}" for path, length in offenders)
        raise RuntimeError(
            "formal evidence path exceeds the legacy Windows path budget; "
            "refusing publication before the manifest switch: "
            + details
        )


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
    staged_canonical, staged_trace = _staged_output_paths(output, token)
    staged_trace_atomic = staged_trace.with_name(
        f".{staged_trace.name}.{'f' * 32}.staging"
    )
    _require_windows_path_budget(
        output,
        metrics_path,
        staged_canonical,
        staged_trace,
        staged_trace_atomic,
    )
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
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="write a current-fingerprint source-geometry preflight artifact and stop",
    )
    parser.add_argument("--list-scenes", action="store_true")
    parser.add_argument(
        "--profile",
        choices=(FINAL_LADDER_PROFILE_ID, MULTI_SEED_NIGHTLY_PROFILE_ID),
        help="run a preregistered formal control profile",
    )
    return parser.parse_args()


def _formal_control_config(
    base: SceneConfig,
    control: FormalControlSpec,
) -> SceneConfig:
    return replace(
        base,
        minutes=control.minutes,
        demand_minutes=control.demand_minutes,
        entry_count_hour=control.entry_count_hour,
        exit_count_hour=control.exit_count_hour,
        seed=control.seed,
    )


def _execute_formal_control(
    *,
    base: SceneConfig,
    control: FormalControlSpec,
    output: Path,
) -> FormalControlExecution:
    config = _formal_control_config(base, control)
    trace, final_metrics, design_sha256, metro_fingerprint, analysis_fingerprint = (
        _run_simulation(
            config,
            formal_horizon_steps=control.horizon_steps,
            require_final_acceptance=control.require_final_acceptance,
            expected_departed_trains=control.expected_departed_trains,
        )
    )
    result = _write_run_outputs(
        output=output,
        config=config,
        trace=trace,
        final_metrics=final_metrics,
        design_sha256=design_sha256,
        metro_runtime_fingerprint=metro_fingerprint,
        analysis_runtime_fingerprint_at_start=analysis_fingerprint,
    )
    return FormalControlExecution(
        control=control,
        canonical_path=result.canonical_path,
        manifest_path=result.metrics_path,
        trace_path=result.trace_path,
        scene_config_sha256=scene_config_sha256(config),
        design_sha256=design_sha256,
        metro_runtime_fingerprint=metro_fingerprint,
        analysis_runtime_fingerprint=analysis_fingerprint,
    )


def _run_formal_profile(*, args: argparse.Namespace, base: SceneConfig) -> None:
    forbidden = []
    if args.minutes is not None:
        forbidden.append("--minutes")
    if args.reuse_existing_trace:
        forbidden.append("--reuse-existing-trace")
    if args.preflight_only:
        forbidden.append("--preflight-only")
    if forbidden:
        raise SystemExit("formal profiles do not support: " + ", ".join(forbidden))

    if args.profile == FINAL_LADDER_PROFILE_ID:
        if args.seed is not None:
            raise SystemExit("the final ladder seed is frozen by its profile")
        profile = final_ladder_profile()
        _, design_sha256 = build_metro_scenario(base)
        result = execute_final_ladder(
            profile=profile,
            output=args.output,
            base_scene_config_sha256=scene_config_sha256(base),
            design_sha256=design_sha256,
            metro_runtime_fingerprint=metro_source_fingerprint(),
            analysis_runtime_fingerprint=analysis_runtime_fingerprint(),
            run_control=lambda control, output: _execute_formal_control(
                base=base,
                control=control,
                output=output,
            ),
            current_fingerprints=lambda: (
                metro_source_fingerprint(),
                analysis_runtime_fingerprint(),
            ),
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "profile": profile.profile_id,
                    "active_manifest": str(result.active_manifest_path),
                    "ladder_manifest": str(result.ladder_manifest_path),
                },
                ensure_ascii=False,
            )
        )
        return

    if args.seed is None:
        raise SystemExit("the multi-seed nightly profile requires --seed")
    profile = multi_seed_nightly_profile(args.seed)
    execution = _execute_formal_control(
        base=base,
        control=profile.controls[0],
        output=args.output,
    )
    payload = json.loads(execution.manifest_path.read_bytes())
    payload["runner_provenance"] = {
        "mode": "formal_control_profile",
        "runner": "scripts/run_alignment_scene.py",
        "profile_id": profile.profile_id,
        "profile_sha256": profile.sha256,
        "control_id": execution.control.control_id,
        "control_spec_sha256": execution.control.sha256,
        "publication_scope": profile.publication_scope,
        "trace_replay": False,
        "manual_model_step": False,
    }
    _write_json(execution.manifest_path, payload)
    print(
        json.dumps(
            {
                "status": "ok",
                "profile": profile.profile_id,
                "seed": args.seed,
                "manifest": str(execution.manifest_path),
            },
            ensure_ascii=False,
        )
    )


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
    if args.profile is not None:
        if config.scene_id != "platform_boarding":
            raise SystemExit("formal Step 5 profiles are registered only for platform_boarding")
        _run_formal_profile(args=args, base=config)
        return
    try:
        config = _apply_cli_overrides(
            config,
            seed=args.seed,
            minutes=args.minutes,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.preflight_only:
        scenario, _ = build_metro_scenario(config)
        report = alignment_source_geometry_preflight(scenario)
        path = _write_source_preflight_artifact(
            output=args.output,
            config=config,
            report=report,
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "scene_id": config.scene_id,
                    "preflight": str(path),
                },
                ensure_ascii=False,
            )
        )
        if report["status"] != "pass":
            raise AlignmentSourceGeometryConflict(report)
        admission_report = alignment_entry_admission_preflight(scenario)
        admission_path = _write_admission_preflight_artifact(
            output=args.output,
            config=config,
            report=admission_report,
        )
        print(f"admission preflight: {admission_path}")
        if admission_report["status"] != "pass":
            raise AlignmentAdmissionCapacityConflict(admission_report)
        return
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
    except AlignmentAdmissionCapacityConflict as exc:
        blocker_path = _write_admission_preflight_artifact(
            output=args.output,
            config=config,
            report=exc.report,
        )
        print(f"admission preflight blocker: {blocker_path}")
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
