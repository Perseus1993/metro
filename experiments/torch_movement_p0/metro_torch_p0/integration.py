"""Read-only Metro boundary smoke test for the isolated P0 backend."""

from __future__ import annotations

from dataclasses import dataclass

from .metro_adapter import ExperimentalTorchMovementBackend


@dataclass(frozen=True)
class MetroBoundaryEvidence:
    injected: bool
    progressed_m: float
    active_slots: int
    passed: bool


def run_metro_boundary_smoke(device: str) -> MetroBoundaryEvidence:
    """Instantiate Metro with dependency injection and exercise one walking agent.

    This does not alter Metro's source, default backend selection, facilities,
    goals, queues, or trains.  It is intentionally only an interface proof.
    """
    from metro_station.adapters.simulation.agents.passenger import PassengerAgent
    from metro_station.adapters.simulation.design.templates import create_design
    from metro_station.adapters.simulation.planning.plan import AgentIntent
    from metro_station.adapters.simulation.runtime.mesa_model import MetroStationModel
    from metro_station.adapters.simulation.station.scenario import StationSandboxScenario

    scenario = StationSandboxScenario(
        station_name="torch_p0_boundary_smoke",
        hour=8,
        minutes=1,
        tick_seconds=1,
        group_size=1,
        entry_count_hour=0,
        exit_count_hour=0,
        source_label="torch_p0",
        sample_hours=1,
        station_design=create_design("two_level_island_platform"),
        simulation_clock_mode="physical",
        audit_enabled=False,
        audit_print_events=False,
    )
    backend = ExperimentalTorchMovementBackend(capacity=8, device=device)
    model = MetroStationModel(scenario, seed=19, movement_backend=backend)
    passenger = PassengerAgent(
        model,
        group_size=1,
        created_step=0,
        intent=AgentIntent.ENTER_AND_BOARD,
    )
    model.passengers.append(passenger)
    start = passenger.pos
    passenger.target = model.clamp_position((start[0] + 4.0, start[1]))
    for _ in range(20):
        result = backend.step_all([passenger])[0][1]
        passenger.pos = result.position
    progressed = ((passenger.pos[0] - start[0]) ** 2 + (passenger.pos[1] - start[1]) ** 2) ** 0.5
    active_slots = len(backend.active_passenger_ids())
    injected = model.movement_backend is backend
    return MetroBoundaryEvidence(
        injected=injected,
        progressed_m=progressed,
        active_slots=active_slots,
        passed=injected and progressed > 0.05 and active_slots == 1,
    )
