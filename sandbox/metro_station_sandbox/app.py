from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

from .runtime.data_loader import load_station_hour_profile
from .design.templates import create_design
from .runtime.mesa_model import MetroStationModel
from .station.scenario import StationSandboxScenario
from .design_inspector import serve_design_inspector
from .visual_demo.config import ROOT as VISUAL_DEMO_ROOT
from .visual_demo.config import TRACKS_JS
from .visual_demo.mesa_export import write_mesa_visual_tracks_js

if TYPE_CHECKING:
    from .design.schema import StationDesignDocument


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Mesa+JuPedSim and export the animation_demo visual payload."
    )
    parser.add_argument("--station", default="小寨", help="Station name in ADS station panel.")
    parser.add_argument("--hour", type=int, default=18, help="Scenario hour, 0-23.")
    parser.add_argument(
        "--minutes",
        type=int,
        default=1,
        help=(
            "Demand minutes when --clearance-minutes is set; otherwise total simulated minutes."
        ),
    )
    parser.add_argument(
        "--demand-minutes",
        type=int,
        default=None,
        help="Minutes over which passenger demand is generated. Defaults to --minutes.",
    )
    parser.add_argument(
        "--clearance-minutes",
        type=int,
        default=0,
        help="Extra minutes to keep simulating after demand generation stops.",
    )
    parser.add_argument(
        "--tick-seconds", type=int, default=5, help="Seconds represented by one step."
    )
    parser.add_argument(
        "--group-size", type=int, default=1, help="Passengers represented by one dot."
    )
    parser.add_argument(
        "--entry-count-hour",
        type=int,
        default=None,
        help="Override hourly entering demand. Useful for controlled trajectory checks.",
    )
    parser.add_argument(
        "--exit-count-hour",
        type=int,
        default=None,
        help="Override hourly alighting-to-exit demand. Useful for controlled trajectory checks.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--design-template",
        default="visual_demo_station",
        help="StationDesignDocument template id to compile into the Mesa simulation graph.",
    )
    parser.add_argument(
        "--movement-backend",
        choices=("jupedsim", "batched_jupedsim", "micro_jupedsim"),
        default="jupedsim",
        help=(
            "Mesa movement engine. jupedsim is the batched-by-target backend; "
            "micro_jupedsim keeps the older per-agent backend."
        ),
    )
    parser.add_argument(
        "--jupedsim-model",
        choices=("collision_free_speed", "social_force"),
        default="collision_free_speed",
        help="JuPedSim operational pedestrian model used inside each walking tick.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Disable structured audit lines for diagnostic events.",
    )
    parser.add_argument("--admins", type=int, default=0, help="Number of staff/admin agents.")
    parser.add_argument(
        "--tracks-out",
        type=Path,
        default=TRACKS_JS,
        help="JPS_TRACKS JavaScript payload consumed by animation_demo.html.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve animation_demo.html over local HTTP after exporting tracks.",
    )
    parser.add_argument(
        "--serve-inspector",
        action="store_true",
        help="Serve the React Flow station design inspector without running simulation.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for --serve.")
    parser.add_argument("--port", type=int, default=8765, help="Port for --serve.")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Deprecated; use --tracks-out. Kept only so old commands fail less abruptly.",
    )
    return parser


def make_scenario(
    args: argparse.Namespace,
    *,
    station_design: "StationDesignDocument | None" = None,
) -> StationSandboxScenario:
    profile = load_station_hour_profile(
        args.station,
        args.hour,
        audit_enabled=not args.no_audit,
    )
    demand_minutes = max(1, int(args.demand_minutes or args.minutes))
    clearance_minutes = max(0, int(args.clearance_minutes or 0))
    if args.demand_minutes is not None or clearance_minutes > 0:
        total_minutes = max(int(args.minutes), demand_minutes + clearance_minutes)
    else:
        total_minutes = max(1, int(args.minutes))

    return StationSandboxScenario(
        station_name=profile.station_name,
        hour=profile.hour,
        minutes=total_minutes,
        demand_minutes=demand_minutes if demand_minutes != total_minutes else None,
        tick_seconds=args.tick_seconds,
        group_size=args.group_size,
        entry_count_hour=(
            profile.entry_count_hour
            if args.entry_count_hour is None
            else max(0, args.entry_count_hour)
        ),
        exit_count_hour=(
            profile.exit_count_hour
            if args.exit_count_hour is None
            else max(0, args.exit_count_hour)
        ),
        source_label=profile.source_label,
        sample_hours=profile.sample_hours,
        station_design=station_design or create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        jupedsim_strict=True,
        audit_enabled=not args.no_audit,
        audit_print_events=not args.no_audit,
        admin_agent_count=max(0, args.admins),
    )


def visual_demo_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/animation_demo.html"


def main() -> None:
    args = build_parser().parse_args()
    if args.serve_inspector:
        serve_design_inspector(args.host, args.port)
        return

    tracks_out = args.out or args.tracks_out
    if args.out is not None:
        print("[SANDBOX] --out is deprecated; writing animation_demo tracks there.")

    scenario = make_scenario(args)
    model = MetroStationModel(scenario, seed=args.seed)
    frames = model.run()
    payload = write_mesa_visual_tracks_js(
        frames=frames,
        scenario=scenario,
        output_path=tracks_out,
        facilities=model.facilities,
        service_events=model.facility_service_events,
    )
    final = frames[-1]["metrics"] if frames else {}
    print(f"[SANDBOX] station={scenario.station_name} hour={scenario.hour}")
    print(
        f"[SANDBOX] entry_count_hour={scenario.entry_count_hour} sample_hours={scenario.sample_hours}"
    )
    print(f"[SANDBOX] exit_count_hour={scenario.exit_count_hour}")
    print(f"[SANDBOX] jupedsim={model.jupedsim.status.message}")
    print(f"[SANDBOX] frames={len(frames)}")
    print(f"[SANDBOX] visual_tracks={tracks_out.resolve()}")
    print(f"[SANDBOX] visual_agents={len(payload.get('agents', []))}")
    print(f"[SANDBOX] animation={VISUAL_DEMO_ROOT / 'animation_demo.html'}")
    print(f"[SANDBOX] final_metrics={final}")

    if args.serve:
        handler = lambda *handler_args, **handler_kwargs: SimpleHTTPRequestHandler(  # noqa: E731
            *handler_args,
            directory=str(VISUAL_DEMO_ROOT),
            **handler_kwargs,
        )
        server = ThreadingHTTPServer((args.host, args.port), handler)
        print(f"[SANDBOX] serving={visual_demo_url(args.host, args.port)}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("[SANDBOX] server stopped")


if __name__ == "__main__":
    main()
