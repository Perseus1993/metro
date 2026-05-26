from __future__ import annotations

from dataclasses import dataclass

try:  # Support both package execution and direct script execution.
    from .specs import (
        EXIT_GATE_QUEUE_SPECS,
        FACILITY_QUEUES,
        GATE_QUEUE_SPECS,
        FacilityQueueSpec,
    )
except ImportError:  # pragma: no cover
    from specs import (
        EXIT_GATE_QUEUE_SPECS,
        FACILITY_QUEUES,
        GATE_QUEUE_SPECS,
        FacilityQueueSpec,
    )


@dataclass(frozen=True)
class VisualProcessModel:
    """Facility-process grouping for the JuPedSim visual demo.

    The generator still samples tracks, but queue ownership and process
    categories live here so routing/rendering do not each maintain their own
    partial facility lists.
    """

    entry_gate_queues: tuple[FacilityQueueSpec, ...]
    exit_gate_queues: tuple[FacilityQueueSpec, ...]
    transfer_queues: tuple[FacilityQueueSpec, ...]

    @property
    def native_facility_queues(self) -> tuple[FacilityQueueSpec, ...]:
        return (*self.entry_gate_queues, *self.exit_gate_queues, *self.transfer_queues)

    @property
    def entry_gate_names(self) -> set[str]:
        return {spec.name for spec in self.entry_gate_queues}

    @property
    def exit_gate_names(self) -> set[str]:
        return {spec.name for spec in self.exit_gate_queues}

    @property
    def downstream_boarding_names(self) -> set[str]:
        return {"down_escalator_1_queue", "down_escalator_2_queue", "down_elevator_queue"}

    @property
    def upstream_exit_names(self) -> set[str]:
        return {"up_escalator_1_queue", "up_escalator_2_queue", "stairs_up_queue"}

    def kind_for(self, spec: FacilityQueueSpec) -> str:
        if spec.name.startswith("entry_gate"):
            return "gate"
        if spec.name.startswith("exit_gate"):
            return "exit_gate"
        if spec.name.startswith("down_escalator") or spec.name.startswith("up_escalator"):
            return "escalator"
        if "elevator" in spec.name:
            return "elevator"
        if spec.name.startswith("stairs"):
            return "stairs"
        return "facility"


PROCESS_MODEL = VisualProcessModel(
    entry_gate_queues=GATE_QUEUE_SPECS,
    exit_gate_queues=EXIT_GATE_QUEUE_SPECS,
    transfer_queues=FACILITY_QUEUES,
)
