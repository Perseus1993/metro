from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def write_experiment_report(
    results: Iterable[Any],
    output_dir: Path,
    *,
    replay_asset_dir: Path | None = None,
    replay_url_prefix: str | None = None,
) -> None:
    result_list = list(results)
    output_dir.mkdir(parents=True, exist_ok=True)
    if replay_asset_dir is not None:
        replay_asset_dir.mkdir(parents=True, exist_ok=True)
    summary = [
        _result_summary(
            result,
            output_dir=output_dir,
            replay_asset_dir=replay_asset_dir,
            replay_url_prefix=replay_url_prefix,
        )
        for result in result_list
    ]
    (output_dir / "experiment_results.json").write_text(
        json.dumps({"results": summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "experiment_report.md").write_text(
        _markdown_report(summary),
        encoding="utf-8",
    )


def _result_summary(
    result: Any,
    *,
    output_dir: Path,
    replay_asset_dir: Path | None,
    replay_url_prefix: str | None,
) -> dict[str, Any]:
    case = result.case
    trajectory_report = (
        result.trajectory_report.as_dict()
        if result.trajectory_report is not None
        else None
    )
    metrics = dict(result.metrics or {})
    metrics.update(_peak_queue_metrics(result.frames or []))
    clearance = {}
    if result.tracks_payload is not None:
        raw_clearance = result.tracks_payload.get("clearance_audit")
        clearance = raw_clearance if isinstance(raw_clearance, dict) else {}
    tracks_path, replay_file = _write_tracks_payload(
        result,
        output_dir=output_dir,
        replay_asset_dir=replay_asset_dir,
        replay_url_prefix=replay_url_prefix,
    )
    return {
        "case": {
            "case_id": case.case_id,
            "design_label": case.design_label,
            "entry_count_hour": case.entry_count_hour,
            "exit_count_hour": case.exit_count_hour,
            "transfer_count_hour": getattr(case, "transfer_count_hour", 0),
            "seed": case.seed,
            "minutes": case.minutes,
            "movement_backend": case.movement_backend,
        },
        "status": result.status,
        "metrics": metrics,
        "clearance": clearance,
        "trajectory_report": trajectory_report,
        "error": result.error,
        "tracks_path": str(tracks_path) if tracks_path is not None else None,
        "replay_file": replay_file,
        "frame_count": len(result.frames or []),
        "track_count": len(result.tracks_payload.get("agents", []))
        if result.tracks_payload is not None
        else 0,
    }


def _markdown_report(summary: list[dict[str, Any]]) -> str:
    lines = [
        "# Metro Experiment Report",
        "",
        "| case | design | entry/h | exit/h | transfer/h | seed | status | completion | remaining | avg system min | max gate q | max vertical q | stuck | trajectory | replay file | issues |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in summary:
        case = row["case"]
        metrics = row.get("metrics", {})
        clearance = row.get("clearance", {})
        trajectory = row.get("trajectory_report") or {}
        issues = trajectory.get("issues") or ([row["error"]] if row.get("error") else [])
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(case["case_id"]),
                    _cell(case["design_label"]),
                    str(case["entry_count_hour"]),
                    str(case["exit_count_hour"]),
                    str(case["transfer_count_hour"]),
                    str(case["seed"]),
                    _cell(row["status"]),
                    _percent(trajectory.get("completion_rate")),
                    str(_int(clearance.get("remaining_agents", metrics.get("station_persons")))),
                    _number(metrics.get("average_system_minutes")),
                    str(_int(metrics.get("max_gate_queue_persons"))),
                    str(_int(metrics.get("max_vertical_queue_persons"))),
                    str(_int(trajectory.get("stuck_agents"))),
                    _cell(trajectory.get("pass_fail", "n/a")),
                    _cell(row.get("replay_file") or "-"),
                    _cell("; ".join(str(item) for item in issues) or "-"),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _peak_queue_metrics(frames: Iterable[Any]) -> dict[str, int]:
    max_gate = 0
    max_vertical = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        metrics = frame.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        max_gate = max(max_gate, _int(metrics.get("gate_queue_persons")))
        max_vertical = max(max_vertical, _int(metrics.get("vertical_queue_persons")))
    return {
        "max_gate_queue_persons": max_gate,
        "max_vertical_queue_persons": max_vertical,
    }


def _write_tracks_payload(
    result: Any,
    *,
    output_dir: Path,
    replay_asset_dir: Path | None,
    replay_url_prefix: str | None,
) -> tuple[Path | None, str | None]:
    if result.tracks_payload is None:
        return None, None
    file_name = f"{result.case.case_id}_tracks.js"
    tracks_text = (
        "window.JPS_TRACKS = "
        + json.dumps(result.tracks_payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    tracks_path = output_dir / file_name
    tracks_path.write_text(tracks_text, encoding="utf-8")
    if replay_asset_dir is None:
        return tracks_path, file_name

    replay_path = replay_asset_dir / file_name
    replay_path.write_text(tracks_text, encoding="utf-8")
    prefix = (replay_url_prefix or "").strip("/")
    replay_file = f"{prefix}/{file_name}" if prefix else file_name
    return tracks_path, replay_file


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _number(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
