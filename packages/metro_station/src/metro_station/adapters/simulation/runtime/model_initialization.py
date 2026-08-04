from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import mesa

from ..agents.passenger import PassengerAgent
from ..agents.staff import AdminAgent
from ..agents.transit import PlatformAgent, TrainAgent
from ..facilities.runtime import FacilityAgent, facility_agent_for_spec
from ..facilities.vertical_transport_base import (
    VerticalPhysicalResource,
    VerticalTransportProcessAgent,
)
from ..facilities.service_events import FacilityServiceEvent
from ..planning.plan import AgentIntent, FacilityStage
from ..planning.journey_catalog import (
    default_journey_graph_catalog,
    load_journey_graph_catalog,
)
from ..planning.journey_catalog_compiler import compile_journey_graph_catalog
from .progress_monitor import ProgressMonitor
from ..movement.backend import MovementBackend
from ..movement.facility_motion_trace import FacilityMotionTraceRecorder
from ..movement.jps_adapter import JuPedSimAdapter
from ..station.scenario import StationSandboxScenario
from ..station.disruptions import validate_facility_availability_events
from .audit import AuditLogger
from .control_timeline import ControlTimelineController
from .demand_scheduler import DemandScheduler
from .disruptions import FacilityDisruptionController
from .evacuation_routing_runtime import RuntimeEvacuationRoutingService
from .goal_parity import GoalParityRecorder
from .metrics import (
    average_system_minutes,
    average_walk_speed_factor,
    crowding_index,
    gate_queue_persons,
    platform_waiting_persons,
    station_persons,
    vertical_queue_persons,
)
from .passenger_goal_coordinator import PassengerGoalCoordinator
from .passenger_goal_runtime import PassengerGoalRuntime
from .simulation_clock import SimulationClock
from .snapshots import SnapshotBuilder
from .step_orchestrator import SimulationStepOrchestrator
from .terminal_events import PassengerTerminalEvent
from .train_disruptions import TrainDisruptionController

if TYPE_CHECKING:
    from metro_station.application.routing_plugins import EvacuationRoutingPort

    from .mesa_model import MetroStationModel


def initialize_metro_station_model(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
    movement_backend: MovementBackend | None,
    design_compiler: Any,
    *,
    routing_algorithm: EvacuationRoutingPort | None = None,
    routing_parameters: Mapping[str, Any] | None = None,
    algorithm_seed: int = 42,
) -> None:
    _initialize_base_state(model, scenario, movement_backend)
    _compile_station(model, scenario, design_compiler)
    model.evacuation_routing = RuntimeEvacuationRoutingService(
        routing_algorithm,
        getattr(model.layout_graph, "station_graph", None),
        parameters=routing_parameters,
        base_seed=algorithm_seed,
    )
    model.routing_decision_logs = []
    model.facility_choice_decision_logs: list[dict[str, Any]] = []
    model.control_timeline_controller = ControlTimelineController(scenario.control_plan)
    _initialize_facilities(model, scenario)
    _initialize_transit(model, scenario)
    _initialize_runtime_services(model, scenario)


def _initialize_base_state(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
    movement_backend: MovementBackend | None,
) -> None:
    model._scenario = scenario
    model.simulation_clock = SimulationClock.from_scenario(scenario)
    model.step_index = 0
    model.passengers: list[PassengerAgent] = []
    model.passenger_goal_runtimes: dict[int, PassengerGoalRuntime] = {}
    model.departed_wait_minutes: list[float] = []
    model.boarded_persons = 0
    model.departed_persons = 0
    model.evacuated_persons = 0
    model.passenger_terminal_events: list[PassengerTerminalEvent] = []
    model.spawned_persons = 0
    model.spawned_persons_by_intent: Counter[str] = Counter()
    model.spawned_persons_by_entrance: Counter[str] = Counter()
    model.walking_cost_source_counts: Counter[str] = Counter()
    model.spatial_capacity_event_counts: Counter[str] = Counter()
    model.walking_cost_evaluation_count = 0
    model.pending_alighting_groups = 0
    model.pending_spawn_groups: Counter[str] = Counter()
    model.max_pending_alighting_groups = 0
    model.frames: list[dict[str, Any]] = []
    model.facility_motion_trace_recorder = FacilityMotionTraceRecorder(
        sample_interval_seconds=scenario.movement_trace_sample_seconds,
    )
    model._spawned_since_last_frame = False
    model.facility_service_events: list[FacilityServiceEvent] = []
    model._facility_service_event_id = 0
    model._evacuation_activated = False
    model.snapshot_builder = SnapshotBuilder()
    model.step_orchestrator = SimulationStepOrchestrator()
    model.audit = AuditLogger(
        enabled=scenario.audit_enabled,
        print_events=scenario.audit_print_events,
    )
    model.jupedsim = JuPedSimAdapter()
    model.movement_backend = movement_backend or model._build_movement_backend()
    model.progress_monitor = ProgressMonitor()
    model._facility_targeting_reservations: dict[str, dict[int, int]] = defaultdict(dict)
    model._facility_targeting_slot_indices: dict[str, dict[int, int]] = defaultdict(dict)
    model._facility_targeting_proof_revisions: dict[str, dict[int, int]] = defaultdict(dict)
    # Private owner registry: keys are created only by the reservation API and
    # removed only by stage/all-owner invalidation.  External code must never
    # migrate or rewrite a (passenger_id, stage) key.
    model._facility_approach_reservation_registry: dict[tuple[int, str], object] = {}
    model._decision_holding_reservations: dict[tuple[int, str], object] = {}
    model._decision_holding_slot_owners: dict[tuple[str, float, float], int] = {}
    model._decision_holding_candidate_cache: dict[object, tuple[tuple[float, float], ...]] = {}
    model._platform_waiting_reservations: dict[int, object] = {}
    model._platform_waiting_slot_owners: dict[tuple[str, float, float], int] = {}
    model._spatial_capacity_slot_owners: dict[str, dict[int, int]] = defaultdict(dict)
    model._walkable_area_revision = 0
    model._facility_approach_proof_revision = 0
    model._facility_approach_proof_cache: dict[object, tuple[int, ...]] = {}
    model._facility_service_start_floors: dict[str, float] = {}


def _compile_station(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
    design_compiler: Any,
) -> None:
    if scenario.station_design is None:
        raise ValueError(
            "StationDesignDocument is required. Pass station_design or use "
            "--design-template in the CLI."
        )
    model.layout_graph = design_compiler.compile(scenario.station_design, scenario)
    model._active_facility_portal_bindings = {
        binding.facility_id: binding
        for binding in getattr(model.layout_graph, "facility_portal_bindings", ())
    }
    station_graph = getattr(model.layout_graph, "station_graph", None)
    model.goal_graph_catalog = (
        load_journey_graph_catalog(scenario.goal_graph_catalog_path)
        if scenario.goal_graph_catalog_path is not None
        else compile_journey_graph_catalog(station_graph)
        if station_graph is not None
        else default_journey_graph_catalog()
    )
    model.goal_graph_catalog.require_intents(tuple(AgentIntent))
    _validate_entry_entrance_weights(model, scenario)


def _validate_entry_entrance_weights(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
) -> None:
    if not scenario.entry_entrance_weights:
        return
    station_graph = getattr(model.layout_graph, "station_graph", None)
    known = {
        str(node.element_id)
        for node in station_graph.nodes_matching(kind="entrance")
        if node.element_id is not None
    }
    configured = {str(element_id) for element_id, _ in scenario.entry_entrance_weights}
    unknown = sorted(configured - known)
    if unknown:
        raise ValueError("entry_entrance_weights contains unknown entrances: " + ", ".join(unknown))


def _initialize_facilities(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
) -> None:
    model.facilities: list[FacilityAgent] = [
        facility_agent_for_spec(model, spec) for spec in model.layout_graph.facilities
    ]
    model.facilities_by_id: dict[str, FacilityAgent] = {
        facility.facility_id: facility for facility in model.facilities
    }
    for facility in model.facilities:
        binding = model.facility_portal_binding(facility.facility_id)
        facility.queue.max_length = binding.declared_queue_capacity
    _bind_vertical_physical_resources(model.facilities)
    unknown = sorted(set(scenario.disabled_facility_ids) - set(model.facilities_by_id))
    if unknown:
        raise ValueError("disabled_facility_ids contains unknown facilities: " + ", ".join(unknown))
    model.control_timeline_controller.validate_model(model)
    facility_events = tuple(
        sorted(
            (
                *scenario.facility_availability_events,
                *model.control_timeline_controller.facility_availability_events(),
            )
        )
    )
    validate_facility_availability_events(
        facility_events,
        horizon_seconds=scenario.horizon_duration_seconds,
        tick_seconds=scenario.tick_seconds,
        statically_disabled_ids=scenario.disabled_facility_ids,
    )
    model.disruption_controller = FacilityDisruptionController(
        facility_events,
        statically_disabled_ids=scenario.disabled_facility_ids,
    )
    model.disruption_controller.validate_facility_ids(model.facilities_by_id)
    model.gates = model._facilities_for_stage(FacilityStage.ENTRY_GATE)
    model.gate = model._require_first(model.gates, "entry gate facility")
    model.exit_gates = model._facilities_for_stage(FacilityStage.EXIT_GATE)
    model.vertical_transports = model._facilities_for_stage(FacilityStage.VERTICAL_TRANSFER)
    model.boarding_doors = model._facilities_for_stage(FacilityStage.BOARDING_DOOR)


def _bind_vertical_physical_resources(facilities: list[FacilityAgent]) -> None:
    resources: dict[str, VerticalPhysicalResource] = {}
    for facility in facilities:
        if (
            not isinstance(facility, VerticalTransportProcessAgent)
            or not facility.requires_exclusive_direction
        ):
            continue
        source_id = str(facility.spec.source_element_id or facility.facility_id)
        resource = resources.setdefault(source_id, VerticalPhysicalResource(source_id))
        facility.bind_physical_resource(resource)


def _initialize_transit(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
) -> None:
    descriptors = model.layout_graph.platform_descriptors()
    model.platforms = [
        PlatformAgent(model, platform_id=pid, line_id=line, direction=direction)
        for pid, line, direction in descriptors
    ]
    model.platforms_by_id = {platform.platform_id: platform for platform in model.platforms}
    model.platform = model._require_first(model.platforms, "platform descriptor")
    model.trains = [
        TrainAgent(model, platform_id=pid, line_id=line, direction=direction)
        for pid, line, direction in descriptors
    ]
    model.trains_by_platform_id = {train.platform_id: train for train in model.trains}
    model.train_disruption_controller = TrainDisruptionController(
        scenario.train_service_events,
        capacity_events=scenario.train_capacity_events,
    )
    model.train_disruption_controller.validate_platform_ids(model.trains_by_platform_id)
    model.train = model._require_first(model.trains, "train service")
    model.admin_agents = [
        AdminAgent(
            model,
            patrol_route=model._admin_patrol_route(index),
            guide_radius=scenario.admin_guide_radius_units,
        )
        for index in range(max(0, scenario.admin_agent_count))
    ]


def _initialize_runtime_services(
    model: MetroStationModel,
    scenario: StationSandboxScenario,
) -> None:
    model._spatial_index: dict[tuple[int, int], list[PassengerAgent]] = {}
    model._spatial_cell_size = max(1.0, scenario.crowd_radius_units)
    model._jupedsim_walkable_area = None
    model._jupedsim_level_walkable_areas: dict[str, Any] = {}
    model.goal_coordinator = PassengerGoalCoordinator(model)
    model.goal_parity = GoalParityRecorder()
    model.demand_scheduler = DemandScheduler.from_scenario(scenario, model.random)
    model.spawn_schedule = model.demand_scheduler.spawn_schedule
    model.alighting_schedule = model.demand_scheduler.alighting_schedule
    model.datacollector = mesa.DataCollector(
        model_reporters={
            "station_persons": station_persons,
            "gate_queue_persons": gate_queue_persons,
            "vertical_queue_persons": vertical_queue_persons,
            "platform_waiting_persons": platform_waiting_persons,
            "boarded_persons": lambda item: item.boarded_persons,
            "average_system_minutes": average_system_minutes,
            "crowding_index": crowding_index,
            "average_walk_speed_factor": average_walk_speed_factor,
        }
    )
