from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from metro_station.adapters.routing_plugins import (
    BaselineEvacuationRouter,
    RoutingPluginProcessHost,
)
from metro_station.application.routing_plugins import manifest_from_json
from metro_station.application.simulation import SimulationRequest, run_simulation

from .runtime.data_loader import load_station_hour_profile
from .design.templates import create_design
from .executor import MesaSimulationExecutor
from .runtime.clearance_detection import build_clearance_debug
from .station.scenario import StationSandboxScenario
from .station.evacuation import EVACUATION_MODE, EvacuationScenarioConfig
from .simulation_outputs.visual_tracks import (
    write_mesa_visual_tracks_js,
    write_replay_payload_json,
)
from .simulation_outputs.unity_replay import write_unity_replay_payload_json

if TYPE_CHECKING:
    from .design.schema import StationDesignDocument


DEFAULT_TRACKS_JS = Path.cwd() / "output" / "metro_station" / "passenger_tracks_jps.js"


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
        "--tick-seconds",
        type=int,
        default=1,
        help="Seconds represented by one process step; research evidence requires 1 second.",
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
    parser.add_argument(
        "--transfer-count-hour",
        type=int,
        default=0,
        help="Override hourly platform-to-platform transfer demand for controlled clearance checks.",
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
        "--clock-mode",
        choices=("physical", "legacy_scaled"),
        default="physical",
        help="Use a physically coupled Mesa/JuPedSim clock or the legacy scaled clock.",
    )
    parser.add_argument(
        "--goal-graph-mode",
        choices=("active",),
        default="active",
        help="Passenger planning mode. Only active Goal Graph authority is supported.",
    )
    parser.add_argument(
        "--goal-graph-config",
        type=Path,
        default=None,
        help="Optional external JSON JourneyGraph catalog.",
    )
    parser.add_argument(
        "--routing-algorithm",
        choices=("builtin_shortest_path", "internal_graph"),
        default="builtin_shortest_path",
        help=(
            "Evacuation-routing authority. builtin_shortest_path uses the versioned "
            "routing port and records every decision; internal_graph is the legacy "
            "unlogged fallback."
        ),
    )
    parser.add_argument(
        "--routing-plugin-manifest",
        type=Path,
        default=None,
        help=(
            "Optional reviewed local algorithm-plugin/v1 manifest. When present it "
            "overrides --routing-algorithm."
        ),
    )
    parser.add_argument(
        "--routing-parameters-json",
        type=_json_object,
        default={},
        help="JSON object passed to the selected routing algorithm.",
    )
    parser.add_argument(
        "--routing-timeout-seconds",
        type=float,
        default=2.0,
        help="Per-request timeout for a local routing plugin.",
    )
    parser.add_argument(
        "--routing-run-timeout-seconds",
        type=float,
        default=3600.0,
        help="Whole-run timeout for a local routing plugin.",
    )
    parser.add_argument(
        "--scenario-mode",
        choices=("operations", "evacuation"),
        default="operations",
        help="Run normal station operations or a platform-origin evacuation.",
    )
    parser.add_argument(
        "--initial-platform-persons",
        type=int,
        default=0,
        help="Initial platform population used only by evacuation mode.",
    )
    parser.add_argument(
        "--alarm-delay-seconds",
        type=float,
        default=0.0,
        help="Delay before the initial evacuation population starts moving.",
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
        default=DEFAULT_TRACKS_JS,
        help="JPS_TRACKS JavaScript payload consumed by animation_demo.html.",
    )
    parser.add_argument(
        "--replay-json-out",
        type=Path,
        default=None,
        help=(
            "Optional plain JSON replay envelope for Unity and other renderer-neutral clients."
        ),
    )
    parser.add_argument(
        "--bundle-json-out",
        type=Path,
        default=None,
        help=(
            "Optional full visualization bundle JSON used for presentation-fidelity "
            "audits. Scientific clients should continue to use --replay-json-out."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Deprecated; use --tracks-out. Kept only so old commands fail less abruptly.",
    )
    return parser


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("routing parameters must be a JSON object")
    return parsed


@contextmanager
def open_routing_algorithm(
    args: argparse.Namespace,
) -> Iterator[tuple[Any | None, Mapping[str, Any]]]:
    algorithm: Any | None
    if args.routing_plugin_manifest is not None:
        manifest_path = args.routing_plugin_manifest.resolve()
        manifest = manifest_from_json(manifest_path.read_text(encoding="utf-8"))
        algorithm = RoutingPluginProcessHost(
            manifest,
            working_directory=manifest_path.parent,
            timeout_seconds=max(0.001, float(args.routing_timeout_seconds)),
            run_timeout_seconds=max(0.001, float(args.routing_run_timeout_seconds)),
        )
    elif args.routing_algorithm == "builtin_shortest_path":
        algorithm = BaselineEvacuationRouter()
    else:
        algorithm = None

    try:
        yield algorithm, dict(args.routing_parameters_json)
    finally:
        close = getattr(algorithm, "close", None)
        if callable(close):
            close()


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

    evacuation = None
    if args.scenario_mode == EVACUATION_MODE:
        evacuation = EvacuationScenarioConfig(
            initial_platform_persons=max(0, int(args.initial_platform_persons)),
            alarm_delay_seconds=max(0.0, float(args.alarm_delay_seconds)),
        )

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
        transfer_count_hour=max(0, args.transfer_count_hour),
        source_label=profile.source_label,
        sample_hours=profile.sample_hours,
        scenario_mode=args.scenario_mode,
        evacuation=evacuation,
        station_design=station_design or create_design(args.design_template),
        movement_backend_name=args.movement_backend,
        jupedsim_operational_model=args.jupedsim_model,
        simulation_clock_mode=args.clock_mode,
        goal_graph_mode=args.goal_graph_mode,
        goal_graph_catalog_path=(
            None if args.goal_graph_config is None else str(args.goal_graph_config)
        ),
        jupedsim_strict=True,
        audit_enabled=not args.no_audit,
        audit_print_events=not args.no_audit,
        admin_agent_count=max(0, args.admins),
    )


def main(arguments: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(arguments)
    tracks_out = args.out or args.tracks_out
    if args.out is not None:
        print("[SANDBOX] --out is deprecated; writing animation_demo tracks there.")

    scenario = make_scenario(args)
    with open_routing_algorithm(args) as (routing_algorithm, routing_parameters):
        execution = run_simulation(
            SimulationRequest(scenario=scenario, seed=args.seed),
            MesaSimulationExecutor(
                routing_algorithm=routing_algorithm,
                routing_parameters=routing_parameters,
            ),
        )
        model = execution.runtime
        frames = execution.frames
        payload = write_mesa_visual_tracks_js(
            frames=frames,
            scenario=scenario,
            output_path=tracks_out,
            facilities=model.facilities,
            service_events=model.facility_service_events,
            terminal_events=model.passenger_terminal_events,
            routing_decision_logs=model.routing_decision_logs,
            clearance_debug=build_clearance_debug(model),
            movement_trace=model.movement_backend.movement_trace(),
        )
    replay_json_path = None
    if args.replay_json_out is not None:
        replay_json_path = write_unity_replay_payload_json(
            payload=payload,
            output_path=args.replay_json_out,
        )
    bundle_json_path = None
    if args.bundle_json_out is not None:
        bundle_json_path = write_replay_payload_json(
            payload=payload,
            output_path=args.bundle_json_out,
        )
    final = frames[-1]["metrics"] if frames else {}
    print(f"[SANDBOX] station={scenario.station_name} hour={scenario.hour}")
    print(
        f"[SANDBOX] entry_count_hour={scenario.entry_count_hour} sample_hours={scenario.sample_hours}"
    )
    print(f"[SANDBOX] exit_count_hour={scenario.exit_count_hour}")
    print(f"[SANDBOX] transfer_count_hour={scenario.transfer_count_hour}")
    print(f"[SANDBOX] jupedsim={model.jupedsim.status.message}")
    print(f"[SANDBOX] simulation_clock={model.simulation_clock.as_dict()}")
    print(f"[SANDBOX] frames={len(frames)}")
    routing_ids = sorted({log.plugin_id for log in model.routing_decision_logs})
    print(
        f"[SANDBOX] routing_plugins={routing_ids or ['internal_graph']} "
        f"decisions={len(model.routing_decision_logs)}"
    )
    print(f"[SANDBOX] visual_tracks={tracks_out.resolve()}")
    if replay_json_path is not None:
        print(f"[SANDBOX] replay_json={replay_json_path.resolve()}")
    if bundle_json_path is not None:
        print(f"[SANDBOX] bundle_json={bundle_json_path.resolve()}")
    print(f"[SANDBOX] visual_agents={len(payload.get('agents', []))}")
    print(f"[SANDBOX] final_metrics={final}")


if __name__ == "__main__":
    main()
