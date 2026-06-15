from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..planning.plan import AgentIntent, AgentState
from ..planning.behavior import behavior_status_for_passenger
from .metrics import (
    average_system_minutes,
    average_walk_speed_factor,
    crowding_index,
    gate_queue_persons,
    platform_waiting_persons,
    station_persons,
    vertical_queue_persons,
)

if TYPE_CHECKING:
    from ..agents.passenger import PassengerAgent
    from ..agents.staff import AdminAgent
    from ..agents.transit import TrainAgent
    from ..facilities.runtime_base import FacilityProcessAgent
    from .mesa_model import MetroStationModel


@dataclass(frozen=True)
class PassengerSnapshot:
    id: int
    x: float
    y: float
    state: str
    intent: str
    goal: dict[str, Any]
    behavior: dict[str, Any]
    platform_id: str | None
    n: int

    @classmethod
    def from_passenger(cls, passenger: PassengerAgent) -> "PassengerSnapshot":
        return cls(
            id=int(passenger.unique_id),
            x=round(float(passenger.pos[0]), 3),
            y=round(float(passenger.pos[1]), 3),
            state=str(passenger.state),
            intent=str(passenger.intent),
            goal=passenger.current_goal.as_dict(),
            behavior=behavior_status_for_passenger(passenger).as_dict(),
            platform_id=passenger.assigned_platform_id,
            n=int(passenger.group_size),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PassengerSnapshot":
        return cls(
            id=int(payload["id"]),
            x=round(float(payload["x"]), 3),
            y=round(float(payload["y"]), 3),
            state=str(payload.get("state", "")),
            intent=str(payload.get("intent", "")),
            goal=dict(payload.get("goal", {})),
            behavior=dict(payload.get("behavior", {})),
            platform_id=_optional_str(payload.get("platform_id")),
            n=int(payload.get("n", 1) or 1),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrainSnapshot:
    id: int
    line_id: str
    direction: str
    platform_id: str
    state: str
    current_load_persons: int
    last_departed_load_persons: int
    departure_elapsed_seconds: float | None
    departed_trains: int

    @classmethod
    def from_train(cls, train: TrainAgent) -> "TrainSnapshot":
        model = train.model
        return cls(
            id=int(train.unique_id),
            line_id=str(train.line_id),
            direction=str(train.direction),
            platform_id=str(train.platform_id),
            state=str(train.state),
            current_load_persons=int(train.current_load_persons),
            last_departed_load_persons=int(train.last_departed_load_persons),
            departure_elapsed_seconds=None
            if train.last_departure_step is None
            else (model.step_index - train.last_departure_step) * model.scenario.tick_seconds,
            departed_trains=int(train.departed_trains),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TrainSnapshot":
        elapsed = payload.get("departure_elapsed_seconds")
        return cls(
            id=int(payload["id"]),
            line_id=str(payload.get("line_id", "")),
            direction=str(payload.get("direction", "")),
            platform_id=str(payload.get("platform_id", "")),
            state=str(payload.get("state", "")),
            current_load_persons=int(payload.get("current_load_persons", 0) or 0),
            last_departed_load_persons=int(payload.get("last_departed_load_persons", 0) or 0),
            departure_elapsed_seconds=None if elapsed is None else float(elapsed),
            departed_trains=int(payload.get("departed_trains", 0) or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdminSnapshot:
    id: int
    x: float
    y: float
    state: str
    guided_count: int

    @classmethod
    def from_admin(cls, admin: AdminAgent) -> "AdminSnapshot":
        return cls(
            id=int(admin.unique_id),
            x=round(float(admin.pos[0]), 3),
            y=round(float(admin.pos[1]), 3),
            state=str(admin.state),
            guided_count=int(admin.guided_count),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "AdminSnapshot":
        return cls(
            id=int(payload["id"]),
            x=round(float(payload["x"]), 3),
            y=round(float(payload["y"]), 3),
            state=str(payload.get("state", "")),
            guided_count=int(payload.get("guided_count", 0) or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FacilitySnapshot:
    id: str
    label: str
    kind: str
    stage: str
    state: str
    queue_persons: int
    active_persons: int
    served_persons: int
    service_persons_per_min: float
    queue_capacity: int

    @classmethod
    def from_facility(cls, facility: FacilityProcessAgent) -> "FacilitySnapshot":
        spec = facility.spec
        return cls(
            id=str(facility.facility_id),
            label=str(spec.label),
            kind=str(spec.kind),
            stage=str(spec.stage),
            state=str(getattr(facility, "state", "")),
            queue_persons=int(facility.queue_persons),
            active_persons=_facility_active_persons(facility),
            served_persons=int(getattr(facility, "served_persons", 0) or 0),
            service_persons_per_min=round(float(facility.effective_service_persons_per_min), 3),
            queue_capacity=_facility_queue_capacity(facility),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FacilitySnapshot":
        return cls(
            id=str(payload.get("id", "")),
            label=str(payload.get("label", "")),
            kind=str(payload.get("kind", "")),
            stage=str(payload.get("stage", "")),
            state=str(payload.get("state", "")),
            queue_persons=_int(payload, "queue_persons"),
            active_persons=_int(payload, "active_persons"),
            served_persons=_int(payload, "served_persons"),
            service_persons_per_min=_float(payload, "service_persons_per_min"),
            queue_capacity=_int(payload, "queue_capacity"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricSnapshot:
    station_persons: int
    gate_queue_persons: int
    vertical_queue_persons: int
    door_queue_persons: int
    platform_waiting_persons: int
    boarded_persons: int
    spawned_persons: int
    spawned_entry_persons: int
    spawned_exit_persons: int
    spawned_transfer_persons: int
    average_system_minutes: float
    crowding_index: float
    average_walk_speed_factor: float
    gate_state: str
    gate_served_persons: int
    exit_gate_served_persons: int
    vertical_served_persons: int
    boarding_door_served_persons: int
    platform_capacity_remaining: int
    train_state: str
    train_load_persons: int
    train_last_departed_load_persons: int
    train_departure_elapsed_seconds: float | None
    departed_trains: int
    train_count: int
    admin_count: int
    admin_guided_passengers: int
    movement_backend: str
    jupedsim_operational_model: str
    jupedsim_steps: int
    jupedsim_batches: int
    audit_counts: dict[str, int]

    @classmethod
    def from_model(cls, model: MetroStationModel) -> "MetricSnapshot":
        scenario = model.scenario
        return cls(
            station_persons=station_persons(model),
            gate_queue_persons=gate_queue_persons(model),
            vertical_queue_persons=vertical_queue_persons(model),
            door_queue_persons=sum(door.queue_persons for door in model.boarding_doors),
            platform_waiting_persons=platform_waiting_persons(model),
            boarded_persons=int(model.boarded_persons),
            spawned_persons=int(model.spawned_persons),
            spawned_entry_persons=int(
                model.spawned_persons_by_intent[AgentIntent.ENTER_AND_BOARD.value]
            ),
            spawned_exit_persons=int(
                model.spawned_persons_by_intent[AgentIntent.EXIT_STATION.value]
            ),
            spawned_transfer_persons=int(
                model.spawned_persons_by_intent[AgentIntent.TRANSFER.value]
            ),
            average_system_minutes=average_system_minutes(model),
            crowding_index=crowding_index(model),
            average_walk_speed_factor=average_walk_speed_factor(model),
            gate_state="open"
            if any(gate.is_open for gate in [*model.gates, *model.exit_gates])
            else "closed",
            gate_served_persons=sum(gate.served_persons for gate in model.gates),
            exit_gate_served_persons=sum(gate.served_persons for gate in model.exit_gates),
            vertical_served_persons=sum(
                transport.served_persons for transport in model.vertical_transports
            ),
            boarding_door_served_persons=sum(
                door.served_persons for door in model.boarding_doors
            ),
            platform_capacity_remaining=sum(
                platform.capacity_remaining for platform in model.platforms
            ),
            train_state=str(model.train.state),
            train_load_persons=int(model.train.current_load_persons),
            train_last_departed_load_persons=int(model.train.last_departed_load_persons),
            train_departure_elapsed_seconds=None
            if model.train.last_departure_step is None
            else (model.step_index - model.train.last_departure_step) * scenario.tick_seconds,
            departed_trains=int(model.train.departed_trains),
            train_count=len(model.trains),
            admin_count=len(model.admin_agents),
            admin_guided_passengers=sum(admin.guided_count for admin in model.admin_agents),
            movement_backend=type(model.movement_backend).__name__,
            jupedsim_operational_model=str(scenario.jupedsim_operational_model),
            jupedsim_steps=int(getattr(model.movement_backend, "jps_step_count", 0) or 0),
            jupedsim_batches=int(getattr(model.movement_backend, "jps_batch_count", 0) or 0),
            audit_counts=dict(model.audit.summary()),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MetricSnapshot":
        return cls(
            station_persons=_int(payload, "station_persons"),
            gate_queue_persons=_int(payload, "gate_queue_persons"),
            vertical_queue_persons=_int(payload, "vertical_queue_persons"),
            door_queue_persons=_int(payload, "door_queue_persons"),
            platform_waiting_persons=_int(payload, "platform_waiting_persons"),
            boarded_persons=_int(payload, "boarded_persons"),
            spawned_persons=_int(payload, "spawned_persons"),
            spawned_entry_persons=_int(payload, "spawned_entry_persons"),
            spawned_exit_persons=_int(payload, "spawned_exit_persons"),
            spawned_transfer_persons=_int(payload, "spawned_transfer_persons"),
            average_system_minutes=_float(payload, "average_system_minutes"),
            crowding_index=_float(payload, "crowding_index"),
            average_walk_speed_factor=_float(payload, "average_walk_speed_factor", 1.0),
            gate_state=str(payload.get("gate_state", "closed")),
            gate_served_persons=_int(payload, "gate_served_persons"),
            exit_gate_served_persons=_int(payload, "exit_gate_served_persons"),
            vertical_served_persons=_int(payload, "vertical_served_persons"),
            boarding_door_served_persons=_int(payload, "boarding_door_served_persons"),
            platform_capacity_remaining=_int(payload, "platform_capacity_remaining"),
            train_state=str(payload.get("train_state", "")),
            train_load_persons=_int(payload, "train_load_persons"),
            train_last_departed_load_persons=_int(payload, "train_last_departed_load_persons"),
            train_departure_elapsed_seconds=_optional_float(
                payload.get("train_departure_elapsed_seconds")
            ),
            departed_trains=_int(payload, "departed_trains"),
            train_count=_int(payload, "train_count"),
            admin_count=_int(payload, "admin_count"),
            admin_guided_passengers=_int(payload, "admin_guided_passengers"),
            movement_backend=str(payload.get("movement_backend", "")),
            jupedsim_operational_model=str(payload.get("jupedsim_operational_model", "")),
            jupedsim_steps=_int(payload, "jupedsim_steps"),
            jupedsim_batches=_int(payload, "jupedsim_batches"),
            audit_counts=dict(payload.get("audit_counts", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrameSnapshot:
    step: int
    time_seconds: float
    passengers: tuple[PassengerSnapshot, ...]
    trains: tuple[TrainSnapshot, ...]
    admins: tuple[AdminSnapshot, ...]
    facilities: tuple[FacilitySnapshot, ...]
    metrics: MetricSnapshot

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FrameSnapshot":
        metrics = payload.get("metrics", {})
        if not isinstance(metrics, Mapping):
            metrics = {}
        return cls(
            step=int(payload.get("step", 0) or 0),
            time_seconds=float(payload.get("time_seconds", 0.0) or 0.0),
            passengers=tuple(
                PassengerSnapshot.from_mapping(item)
                for item in payload.get("passengers", [])
                if isinstance(item, Mapping)
            ),
            trains=tuple(
                TrainSnapshot.from_mapping(item)
                for item in payload.get("trains", [])
                if isinstance(item, Mapping)
            ),
            admins=tuple(
                AdminSnapshot.from_mapping(item)
                for item in payload.get("admins", [])
                if isinstance(item, Mapping)
            ),
            facilities=tuple(
                FacilitySnapshot.from_mapping(item)
                for item in payload.get("facilities", [])
                if isinstance(item, Mapping)
            ),
            metrics=MetricSnapshot.from_mapping(metrics),
        )

    @classmethod
    def from_any(cls, value: "FrameSnapshot | Mapping[str, Any]") -> "FrameSnapshot":
        if isinstance(value, FrameSnapshot):
            return value
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "time_seconds": self.time_seconds,
            "passengers": [passenger.to_dict() for passenger in self.passengers],
            "trains": [train.to_dict() for train in self.trains],
            "admins": [admin.to_dict() for admin in self.admins],
            "facilities": [facility.to_dict() for facility in self.facilities],
            "metrics": self.metrics.to_dict(),
        }

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


class SnapshotBuilder:
    """Encode model runtime state into a stable frame DTO."""

    def build(self, model: MetroStationModel) -> FrameSnapshot:
        return FrameSnapshot(
            step=int(model.step_index),
            time_seconds=model.step_index * model.scenario.tick_seconds,
            passengers=tuple(
                PassengerSnapshot.from_passenger(passenger)
                for passenger in model.passengers
                if passenger.state != AgentState.DEPARTED.value
            ),
            trains=tuple(TrainSnapshot.from_train(train) for train in model.trains),
            admins=tuple(AdminSnapshot.from_admin(admin) for admin in model.admin_agents),
            facilities=tuple(
                FacilitySnapshot.from_facility(facility) for facility in model.facilities
            ),
            metrics=MetricSnapshot.from_model(model),
        )


def _facility_active_persons(facility: FacilityProcessAgent) -> int:
    cabin_load = getattr(facility, "cabin_load_persons", None)
    if cabin_load is not None:
        return int(cabin_load or 0)

    rides = getattr(facility, "active_rides", None)
    if rides is None:
        return 0
    return sum(int(getattr(ride.passenger, "group_size", 1) or 1) for ride in rides)


def _facility_queue_capacity(facility: FacilityProcessAgent) -> int:
    queue_layout = facility.spec.queue_layout
    if queue_layout.slots:
        return len(queue_layout.slots)
    return max(8, min(96, int(queue_layout.per_row) * 4))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int(payload: Mapping[str, Any], key: str, default: int = 0) -> int:
    return int(payload.get(key, default) or default)


def _float(payload: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    return float(payload.get(key, default) or default)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
