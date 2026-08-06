from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from statistics import median
from typing import Any

ATTRIBUTION_PHASES = (
    "travel",
    "queue",
    "service_ready_wait",
    "release_blocked",
    "completion",
)


@dataclass
class AdmissionTimeAttribution:
    """Attribute each owned admission interval to one downstream phase."""

    phase_steps_by_flow_owner: dict[str, dict[Hashable, Counter[str]]] = field(
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
                phase = self._phase_for_owner(
                    passengers.get(owner_id) if isinstance(owner_id, int) else None,
                    gates,
                    release_prefix=str(release_prefix_by_flow[flow]),
                    key=key,
                )
                owner_phases = self.phase_steps_by_flow_owner[str(flow)].setdefault(
                    owner_id, Counter()
                )
                owner_phases[phase] += 1
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
            return "travel"
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
        return "travel"

    def metrics(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for flow, by_owner in sorted(self.phase_steps_by_flow_owner.items()):
            totals = Counter()
            for phases in by_owner.values():
                totals.update(phases)
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
            }
        return result


__all__ = ["ATTRIBUTION_PHASES", "AdmissionTimeAttribution"]
