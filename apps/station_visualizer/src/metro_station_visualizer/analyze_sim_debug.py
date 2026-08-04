from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Support both package execution and direct script execution.
    from .config import OUTPUT_DIR
except ImportError:  # pragma: no cover
    from config import OUTPUT_DIR


DEFAULT_DEBUG_JSON = OUTPUT_DIR / "visual_demo_sim_debug.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect raw JuPedSim/facility debug output.")
    parser.add_argument(
        "--debug-json",
        type=Path,
        default=DEFAULT_DEBUG_JSON,
        help="Debug JSON written by generate_jps_tracks.py.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum stuck windows to print.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    debug_path = args.debug_json.resolve()
    data = json.loads(debug_path.read_text(encoding="utf-8"))
    report = data.get("report", {})
    samples = data.get("samples", [])
    events = data.get("events", [])

    print(f"[SIM DEBUG] file={debug_path}")
    print(f"[SIM DEBUG] samples={len(samples)} events={len(events)}")
    print(f"[SIM DEBUG] event_counts={report.get('event_counts', {})}")
    print(
        "[SIM DEBUG] "
        f"unresolved_stuck_windows={report.get('stuck_window_count', 0)} "
        f"resolved_stuck_windows={report.get('resolved_stuck_window_count', 0)} "
        f"all_stuck_windows={report.get('all_stuck_window_count', 0)}"
    )
    clearance = data.get("clearance_audit", {})
    if isinstance(clearance, dict) and clearance:
        cleared_label = "yes" if clearance.get("cleared") else "no"
        print(
            "[SIM DEBUG] clearance "
            f"cleared={cleared_label} "
            f"demand={clearance.get('demand_duration_s')}s "
            f"final={clearance.get('final_time_s')}s "
            f"completed={clearance.get('completed_agents')}/{clearance.get('total_agents')} "
            f"remaining={clearance.get('remaining_agents')} "
            f"skipped={clearance.get('skipped_agents')}"
        )
        by_family = clearance.get("by_family", {})
        if isinstance(by_family, dict):
            for family, stats in sorted(by_family.items()):
                if not isinstance(stats, dict):
                    continue
                duration = stats.get("duration", {})
                p90 = duration.get("p90_s") if isinstance(duration, dict) else None
                print(
                    "  "
                    f"{family}: completed={stats.get('completed')}/{stats.get('total')} "
                    f"remaining={stats.get('remaining')} p90_duration={p90}s"
                )
    stage_diagnostics = data.get("stage_diagnostics", {})
    if isinstance(stage_diagnostics, dict):
        print(
            "[SIM DEBUG] stage_diagnostics "
            f"components={stage_diagnostics.get('component_count', 'n/a')} "
            f"stages={stage_diagnostics.get('stage_count', 'n/a')} "
            f"queues={stage_diagnostics.get('queue_stage_count', 'n/a')} "
            f"outside={stage_diagnostics.get('outside_stage_count', 'n/a')} "
            f"multi_component={stage_diagnostics.get('multi_component_stage_count', 'n/a')} "
            f"decision_radii={stage_diagnostics.get('decision_stage_count', 'n/a')}"
        )

    last_live = report.get("last_live_by_facility", {})
    if last_live:
        print("[SIM DEBUG] final live facility states:")
        for facility, counts in sorted(last_live.items()):
            print(
                "  "
                f"{facility}: total={counts.get('total', 0)} "
                f"enqueued={counts.get('enqueued', 0)} "
                f"targeting={counts.get('targeting', 0)}"
            )
    last_live_by_stage = report.get("last_live_by_stage", {})
    if isinstance(last_live_by_stage, dict) and last_live_by_stage:
        top_stages = sorted(
            last_live_by_stage.items(),
            key=lambda item: -int(item[1].get("total", 0)) if isinstance(item[1], dict) else 0,
        )[: args.limit]
        print("[SIM DEBUG] final live stage states:")
        for label, counts in top_stages:
            if not isinstance(counts, dict):
                continue
            print(
                "  "
                f"{label}: kind={counts.get('kind')} total={counts.get('total', 0)} "
                f"enqueued={counts.get('enqueued', 0)} "
                f"targeting={counts.get('targeting', 0)}"
            )

    stuck_windows = report.get("stuck_windows", [])
    if stuck_windows:
        print("[SIM DEBUG] unresolved stuck windows:")
        for item in stuck_windows[: args.limit]:
            print(
                "  "
                f"track={item.get('track_id')} sim={item.get('sim_id')} "
                f"location={item.get('location', item.get('facility'))} "
                f"kind={item.get('stage_kind')} "
                f"action={item.get('behavior_action')} "
                f"queue_mode={item.get('queue_mode')} "
                f"target={item.get('target_region')} "
                f"radius={item.get('stage_radius_m')} "
                f"{item.get('from')}s->{item.get('to')}s "
                f"duration={item.get('duration')}s "
                f"disp={item.get('displacement_m')}m "
                f"resolved_by={item.get('resolved_by')}"
            )


if __name__ == "__main__":
    main()
