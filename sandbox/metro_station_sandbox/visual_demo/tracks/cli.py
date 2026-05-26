from __future__ import annotations

import json

from ..config import TRACKS_JS
from .builder import build_tracks
from .constants import DEBUG_JSON


def write_tracks_js() -> tuple[dict[str, object], dict[str, object] | None]:
    TRACKS_JS.parent.mkdir(parents=True, exist_ok=True)
    payload = build_tracks()
    simulation_debug = payload.pop("_simulation_debug", None)
    TRACKS_JS.write_text(
        "window.JPS_TRACKS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    if simulation_debug is not None:
        DEBUG_JSON.parent.mkdir(parents=True, exist_ok=True)
        DEBUG_JSON.write_text(
            json.dumps(simulation_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload, simulation_debug if isinstance(simulation_debug, dict) else None


def print_track_summary(
    payload: dict[str, object],
    simulation_debug: dict[str, object] | None,
) -> None:
    native_agents = sum(
        1 for agent in payload["agents"] if str(agent.get("source", "")).startswith("jupedsim")
    )  # type: ignore[index]
    print(
        f"[JPS TRACKS] agents={len(payload['agents'])} native_jupedsim={native_agents} output={TRACKS_JS}"
    )
    clearance = payload.get("clearance_audit", {})
    if isinstance(clearance, dict):
        cleared_label = "yes" if clearance.get("cleared") else "no"
        print(
            "[JPS CLEARANCE] "
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
                    "[JPS CLEARANCE] "
                    f"{family}: completed={stats.get('completed')}/{stats.get('total')} "
                    f"remaining={stats.get('remaining')} p90_duration={p90}s"
                )
    if simulation_debug is not None:
        report = simulation_debug.get("report", {})
        print(
            "[JPS DEBUG] "
            f"events={len(simulation_debug.get('events', []))} "
            f"stuck_windows={report.get('stuck_window_count', 'n/a') if isinstance(report, dict) else 'n/a'} "
            f"output={DEBUG_JSON}"
        )


def main() -> None:
    payload, simulation_debug = write_tracks_js()
    print_track_summary(payload, simulation_debug)
