from __future__ import annotations

from collections import Counter
from typing import Any

from ..planning.plan import AgentIntent
from ..spatial_capacity_admission import SpatialCapacityAdmissionError
from .external_demand_reservoir import (
    DemandSourceKind,
    TemporaryDemandBlockReason,
)
from .source_publication_transaction import rollback_published_passenger


def spawn_entry_demand(model: Any) -> None:
    due_by_intent = Counter(model.pending_spawn_groups)
    for intent, mirrored in model._mirrored_pending_spawn_groups.items():
        due_by_intent[intent] = max(0, int(due_by_intent[intent]) - int(mirrored))
    model.pending_spawn_groups.clear()
    model._mirrored_pending_spawn_groups.clear()
    due_by_intent.update(model.demand_scheduler.due_by_intent(model.step_index))
    for intent, count in due_by_intent.items():
        for _ in range(int(count)):
            model.external_demand_reservoir.enqueue(
                scheduled_step=int(model.step_index),
                intent=str(intent),
                group_size=int(model.scenario.group_size),
                source_kind=DemandSourceKind.ENTRY,
                source_ref=str(intent),
            )
    pending_round = model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY)
    for ticket in pending_round:
        claim = model.external_demand_reservoir.claim_next(
            DemandSourceKind.ENTRY,
            ticket.source_ref,
            step=int(model.step_index),
        )
        if claim is None:
            continue
        try:
            passenger = model._spawn_passenger(ticket.intent)
        except SpatialCapacityAdmissionError:
            model.external_demand_reservoir.defer(
                claim,
                step=int(model.step_index),
                reason=TemporaryDemandBlockReason.SOURCE_PLACEMENT_BLOCKED,
            )
            break
        except BaseException:
            model.external_demand_reservoir.defer(
                claim,
                step=int(model.step_index),
                reason=TemporaryDemandBlockReason.DOWNSTREAM_CAPACITY_EXHAUSTED,
            )
            raise
        try:
            model.external_demand_reservoir.commit(
                claim,
                passenger_id=int(passenger.unique_id),
                published_step=int(model.step_index),
            )
        except BaseException:
            rollback_published_passenger(model, passenger)
            raise
    mirrored = Counter(
        ticket.intent
        for ticket in model.external_demand_reservoir.pending_tickets(DemandSourceKind.ENTRY)
    )
    model.pending_spawn_groups.update(mirrored)
    model._mirrored_pending_spawn_groups.update(mirrored)


def spawn_alighting_demand(model: Any) -> None:
    newly_due = model.demand_scheduler.due_alightings(model.step_index)
    model._record_alighting_demand_due(newly_due)
    try:
        if newly_due > 0 and not _enqueue_due_alighting_tickets(model, newly_due):
            return
        pending = model.external_demand_reservoir.pending_tickets(
            DemandSourceKind.TRAIN_ALIGHTING
        )
        model.pending_alighting_groups = len(pending)
        if not pending:
            return

        boarding_trains = [train for train in model.trains if train.is_boarding]
        if not boarding_trains:
            model.run_outcome_code = "train_alighting_manifest_unavailable"
            model.running = False
            raise RuntimeError("scheduled alighting demand has no bound boarding train manifest")
        for train in sorted(boarding_trains, key=lambda item: str(item.platform_id)):
            run_ref = model._train_run_ref(train)
            count = len(
                model.external_demand_reservoir.pending_tickets(
                    DemandSourceKind.TRAIN_ALIGHTING,
                    source_ref=run_ref,
                    match_source_ref=True,
                )
            )
            model._spawn_alighting_passengers_for_train(train, count)
        model.pending_alighting_groups = model.external_demand_reservoir.pending_groups(
            DemandSourceKind.TRAIN_ALIGHTING
        )
        model.max_pending_alighting_groups = max(
            model.max_pending_alighting_groups,
            model.pending_alighting_groups,
        )
    finally:
        model._require_alighting_spawn_conservation()


def _enqueue_due_alighting_tickets(model: Any, newly_due: int) -> bool:
    boarding_trains = sorted(
        (train for train in model.trains if train.is_boarding),
        key=lambda item: str(item.platform_id),
    )
    if not boarding_trains:
        model.run_outcome_code = "train_alighting_manifest_unavailable"
        model.running = False
        nominal = next(
            (
                plan
                for plan in model.planned_train_alightings
                if any(int(step) == int(model.step_index) for step, _count in plan.release_schedule)
            ),
            None,
        )
        arrival_step = int(model.step_index if nominal is None else nominal.arrival_step)
        if arrival_step in model.failed_nominal_alighting_arrivals:
            return False
        model.failed_nominal_alighting_arrivals.add(arrival_step)
        groups = int(newly_due if nominal is None else nominal.planned_groups)
        persons = groups * int(model.scenario.group_size)
        model.unbound_not_alighted_persons += persons
        failure = {
            "departure_status": "failed",
            "failure_code": model.run_outcome_code,
            "scheduled_step": int(model.step_index),
            "nominal_arrival_step": arrival_step,
            "planned_alight_persons": persons,
            "not_alighted_persons": persons,
            "departure_policy": "FAIL_CAPACITY",
            "actual_departure_step": None,
        }
        model.train_exchange_failure_rows.append(failure)
        model.audit.record(
            model.run_outcome_code,
            source="train_exchange_manifest",
            severity="error",
            step=model.step_index,
            context=failure,
        )
        return False
    for train, count in zip(
        boarding_trains,
        model._split_count(int(newly_due), len(boarding_trains)),
        strict=True,
    ):
        if train.close_step is None:
            raise RuntimeError("boarding train has no departure deadline")
        run_ref = model._train_run_ref(train)
        if run_ref not in model.train_exchange_manifests:
            raise RuntimeError(f"alighting manifest missing for {run_ref}")
        for _ in range(int(count)):
            model.external_demand_reservoir.enqueue(
                scheduled_step=int(model.step_index),
                intent=AgentIntent.EXIT_STATION.value,
                group_size=int(model.scenario.group_size),
                source_kind=DemandSourceKind.TRAIN_ALIGHTING,
                source_ref=run_ref,
                departure_deadline_step=int(train.close_step),
            )
    return True


__all__ = ["spawn_alighting_demand", "spawn_entry_demand"]
