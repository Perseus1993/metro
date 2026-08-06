from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from math import hypot
from statistics import median
from typing import Any

ATTRIBUTION_PHASES = (
    "pre_gate_moving",
    "pre_gate_stationary",
    "upstream_wait",
    "upstream_service",
    "queue",
    "service_ready_wait",
    "release_blocked",
    "completion",
    "unclassified",
)

_UPSTREAM_WAIT_STATES = {
    "queueing_vertical",
    "waiting_capacity",
    "waiting_platform",
    "queueing_door",
    "boarding_train",
}
_UPSTREAM_SERVICE_STATES = {"riding_vertical"}
_MOTION_EPSILON_MPS = 1e-6


@dataclass
class AdmissionTimeAttribution:
    """Attribute each owned admission interval to one downstream phase."""

    phase_steps_by_flow_owner: dict[str, dict[Hashable, Counter[str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    state_steps_by_flow_owner: dict[str, dict[Hashable, Counter[str]]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    _last_observed_step_by_flow_owner: dict[tuple[str, Hashable], int] = field(default_factory=dict)
    _blocked_seconds_by_flow_owner: dict[tuple[str, Hashable], float] = field(default_factory=dict)

    def observe(
        self,
        model: Any,
        *,
        release_prefix_by_flow: Mapping[str, str],
    ) -> None:
        interval_end_step = int(model.step_index)
        passengers = {int(passenger.unique_id): passenger for passenger in model.passengers}
        gates = (*model.gates, *model.exit_gates)
        for flow, resource in model.alignment_admission_resources.items():
            for owner_id in resource.owners:
                key = (str(flow), owner_id)
                if self._last_observed_step_by_flow_owner.get(key) == interval_end_step:
                    continue
                passenger = passengers.get(owner_id) if isinstance(owner_id, int) else None
                phase = self._phase_for_owner(
                    passenger,
                    gates,
                    release_prefix=str(release_prefix_by_flow[flow]),
                    key=key,
                )
                owner_phases = self.phase_steps_by_flow_owner[str(flow)].setdefault(
                    owner_id, Counter()
                )
                owner_phases[phase] += 1
                owner_states = self.state_steps_by_flow_owner[str(flow)].setdefault(
                    owner_id, Counter()
                )
                owner_states[self._state_label(passenger)] += 1
                self._last_observed_step_by_flow_owner[key] = interval_end_step

    def _phase_for_owner(
        self,
        passenger: Any | None,
        gates: tuple[Any, ...],
        *,
        release_prefix: str,
        key: tuple[str, Hashable],
    ) -> str:
        if passenger is None:
            return "unclassified"
        completed = str(getattr(passenger, "last_completed_facility_id", None) or "")
        if completed.startswith(release_prefix):
            return "completion"
        for gate in gates:
            active = next(
                (item for item in gate.active_passes if item.passenger is passenger),
                None,
            )
            if active is None:
                continue
            blocked_seconds = float(getattr(active, "blocked_seconds", 0.0))
            previous = self._blocked_seconds_by_flow_owner.get(key, 0.0)
            self._blocked_seconds_by_flow_owner[key] = blocked_seconds
            if blocked_seconds > previous + 1e-12:
                return "release_blocked"
            return "completion"
        for gate in gates:
            if passenger not in gate.queue:
                continue
            is_head = bool(gate.queue) and gate.queue[0] is passenger
            if is_head and gate._passenger_ready_for_service(passenger):
                return "service_ready_wait"
            return "queue"
        state = str(getattr(passenger, "state", "") or "")
        if state in _UPSTREAM_WAIT_STATES:
            return "upstream_wait"
        if state in _UPSTREAM_SERVICE_STATES:
            return "upstream_service"
        velocity = getattr(passenger, "last_walk_velocity_mps", None)
        if velocity is None or len(velocity) != 2:
            return "unclassified"
        speed = hypot(float(velocity[0]), float(velocity[1]))
        if speed > _MOTION_EPSILON_MPS:
            return "pre_gate_moving"
        return "pre_gate_stationary"

    @staticmethod
    def _state_label(passenger: Any | None) -> str:
        if passenger is None:
            return "missing_passenger"
        return str(getattr(passenger, "state", "") or "unknown_state")

    def metrics(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for flow, by_owner in sorted(self.phase_steps_by_flow_owner.items()):
            totals = Counter()
            for phases in by_owner.values():
                totals.update(phases)
            state_by_owner = self.state_steps_by_flow_owner.get(flow, {})
            state_totals = Counter()
            for states in state_by_owner.values():
                state_totals.update(states)
            result[flow] = {
                "owners": len(by_owner),
                "phase_total_steps": {phase: int(totals[phase]) for phase in ATTRIBUTION_PHASES},
                "phase_mean_steps": {
                    phase: (
                        sum(phases[phase] for phases in by_owner.values()) / len(by_owner)
                        if by_owner
                        else 0.0
                    )
                    for phase in ATTRIBUTION_PHASES
                },
                "phase_median_steps": {
                    phase: (
                        float(median(phases[phase] for phases in by_owner.values()))
                        if by_owner
                        else 0.0
                    )
                    for phase in ATTRIBUTION_PHASES
                },
                "owner_phase_steps": {
                    str(owner): {phase: int(phases[phase]) for phase in ATTRIBUTION_PHASES}
                    for owner, phases in sorted(by_owner.items(), key=lambda item: str(item[0]))
                },
                "state_total_steps": {
                    state: int(steps) for state, steps in sorted(state_totals.items())
                },
                "owner_state_steps": {
                    str(owner): {state: int(steps) for state, steps in sorted(states.items())}
                    for owner, states in sorted(
                        state_by_owner.items(), key=lambda item: str(item[0])
                    )
                },
            }
        return result


__all__ = ["ATTRIBUTION_PHASES", "AdmissionTimeAttribution"]
