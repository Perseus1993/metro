from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Hashable
from dataclasses import dataclass
from enum import StrEnum


class DemandSourceKind(StrEnum):
    ENTRY = "entry"
    TRAIN_ALIGHTING = "train_alighting"


class TemporaryDemandBlockReason(StrEnum):
    ADMISSION_CREDIT_EXHAUSTED = "admission_credit_exhausted"
    DOWNSTREAM_CAPACITY_EXHAUSTED = "downstream_capacity_exhausted"
    SOURCE_PLACEMENT_BLOCKED = "source_placement_blocked"


class DemandTicketState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    PUBLISHED = "published"
    NOT_ALIGHTED = "not_alighted"
    RIGHT_CENSORED = "right_censored"


class InvalidDemandConfiguration(ValueError):
    """Demand cannot be represented by the configured source boundary."""


class DemandReservoirStateError(RuntimeError):
    """A claim or publication violates reservoir ownership."""


@dataclass(frozen=True)
class DemandTicket:
    sequence_id: int
    scheduled_step: int
    intent: str
    group_size: int
    source_kind: DemandSourceKind
    source_ref: str | None
    departure_deadline_step: int | None = None

    @property
    def boundary(self) -> tuple[DemandSourceKind, str | None]:
        return self.source_kind, self.source_ref


@dataclass(frozen=True)
class DemandClaim:
    claim_id: int
    ticket: DemandTicket
    claimed_step: int


@dataclass(frozen=True)
class DemandDeferral:
    ticket_id: int
    claim_id: int
    step: int
    reason: TemporaryDemandBlockReason


@dataclass(frozen=True)
class DemandResidence:
    ticket: DemandTicket
    released_step: int
    outcome: DemandTicketState
    release_reason: str
    passenger_id: Hashable | None = None

    @property
    def residence_steps(self) -> int:
        return self.released_step - self.ticket.scheduled_step

    @property
    def right_censored(self) -> bool:
        return self.outcome == DemandTicketState.RIGHT_CENSORED


class ExternalDemandReservoir:
    """Own scheduled demand until one source boundary publishes it exactly once."""

    def __init__(self) -> None:
        self._next_sequence_id = 0
        self._next_claim_id = 0
        self._tickets: dict[int, DemandTicket] = {}
        self._states: dict[int, DemandTicketState] = {}
        self._queues: dict[tuple[DemandSourceKind, str | None], deque[int]] = defaultdict(deque)
        self._active_claim_by_ticket: dict[int, DemandClaim] = {}
        self._published_ticket_by_passenger: dict[Hashable, int] = {}
        self._train_deadline_by_ref: dict[str, int] = {}
        self._expired_train_refs: set[str] = set()
        self._residences: list[DemandResidence] = []
        self._deferrals: list[DemandDeferral] = []
        self._closed = False

    def enqueue(
        self,
        *,
        scheduled_step: int,
        intent: str,
        group_size: int,
        source_kind: DemandSourceKind,
        source_ref: str | None = None,
        departure_deadline_step: int | None = None,
    ) -> DemandTicket:
        self._require_open()
        self._validate_configuration(
            scheduled_step, intent, group_size, source_kind, source_ref, departure_deadline_step
        )
        ticket = DemandTicket(
            sequence_id=self._next_sequence_id,
            scheduled_step=scheduled_step,
            intent=intent,
            group_size=group_size,
            source_kind=source_kind,
            source_ref=source_ref,
            departure_deadline_step=departure_deadline_step,
        )
        self._next_sequence_id += 1
        self._tickets[ticket.sequence_id] = ticket
        self._states[ticket.sequence_id] = DemandTicketState.PENDING
        self._queues[ticket.boundary].append(ticket.sequence_id)
        return ticket

    def peek_head(
        self,
        source_kind: DemandSourceKind,
        source_ref: str | None = None,
    ) -> DemandTicket | None:
        queue = self._queues.get((source_kind, source_ref))
        return None if not queue else self._tickets[queue[0]]

    def claim_next(
        self,
        source_kind: DemandSourceKind,
        source_ref: str | None = None,
        *,
        step: int,
    ) -> DemandClaim | None:
        self._require_open()
        current_step = _require_step(step, "claim step")
        ticket = self.peek_head(source_kind, source_ref)
        if ticket is None:
            return None
        if (
            ticket.departure_deadline_step is not None
            and current_step >= ticket.departure_deadline_step
        ):
            self.expire_train_arrival(str(ticket.source_ref), step=current_step)
            return None
        if current_step < ticket.scheduled_step:
            raise DemandReservoirStateError("demand cannot be claimed before its scheduled step")
        if self._states[ticket.sequence_id] == DemandTicketState.CLAIMED:
            raise DemandReservoirStateError("FIFO head already has an active claim")
        claim = DemandClaim(self._next_claim_id, ticket, current_step)
        self._next_claim_id += 1
        self._states[ticket.sequence_id] = DemandTicketState.CLAIMED
        self._active_claim_by_ticket[ticket.sequence_id] = claim
        return claim

    def defer(
        self,
        claim: DemandClaim,
        *,
        step: int,
        reason: TemporaryDemandBlockReason,
    ) -> None:
        current_step = _require_step(step, "defer step")
        if not isinstance(reason, TemporaryDemandBlockReason):
            raise TypeError("temporary demand block reason must be typed")
        self._require_active_claim(claim)
        self._require_not_before_claim(claim, current_step)
        deadline = claim.ticket.departure_deadline_step
        if deadline is not None and current_step >= deadline:
            self.expire_train_arrival(str(claim.ticket.source_ref), step=current_step)
            return
        self._active_claim_by_ticket.pop(claim.ticket.sequence_id)
        self._states[claim.ticket.sequence_id] = DemandTicketState.PENDING
        self._deferrals.append(
            DemandDeferral(claim.ticket.sequence_id, claim.claim_id, current_step, reason)
        )

    def commit(
        self,
        claim: DemandClaim,
        *,
        passenger_id: Hashable,
        published_step: int,
    ) -> DemandResidence:
        step = self.validate_commit(
            claim,
            passenger_id=passenger_id,
            published_step=published_step,
        )
        self._pop_claimed_head(claim)
        self._published_ticket_by_passenger[passenger_id] = claim.ticket.sequence_id
        return self._record_residence(
            claim.ticket,
            step,
            DemandTicketState.PUBLISHED,
            "published",
            passenger_id,
        )

    def validate_commit(
        self,
        claim: DemandClaim,
        *,
        passenger_id: Hashable,
        published_step: int,
    ) -> int:
        """Validate publication while retaining reservoir ownership."""

        step = _require_step(published_step, "publication step")
        self._require_active_claim(claim)
        self._require_not_before_claim(claim, step)
        if (
            claim.ticket.departure_deadline_step is not None
            and step >= claim.ticket.departure_deadline_step
        ):
            raise DemandReservoirStateError("train alighting demand cannot publish at departure")
        try:
            hash(passenger_id)
        except TypeError as exc:
            raise TypeError("passenger_id must be hashable") from exc
        if passenger_id in self._published_ticket_by_passenger:
            raise DemandReservoirStateError("passenger_id already owns a published demand ticket")
        return step

    def expire_train_arrival(self, source_ref: str, *, step: int) -> tuple[DemandResidence, ...]:
        current_step = _require_step(step, "departure step")
        deadline = self._train_deadline_by_ref.get(source_ref)
        if deadline is None:
            raise InvalidDemandConfiguration("unknown train arrival reference")
        if current_step < deadline:
            raise DemandReservoirStateError("train arrival cannot expire before its deadline")
        boundary = (DemandSourceKind.TRAIN_ALIGHTING, source_ref)
        queue = self._queues.pop(boundary, deque())
        retired = tuple(
            self._retire_unpublished(
                self._tickets[ticket_id],
                deadline,
                DemandTicketState.NOT_ALIGHTED,
                "train_alighting_capacity_insufficient",
            )
            for ticket_id in queue
        )
        self._expired_train_refs.add(source_ref)
        return retired

    def close(self, step: int) -> tuple[DemandResidence, ...]:
        if self._closed:
            return ()
        current_step = _require_step(step, "close step")
        outstanding = sorted(ticket_id for queue in self._queues.values() for ticket_id in queue)
        if any(
            current_step < self._tickets[ticket_id].scheduled_step
            or (
                (claim := self._active_claim_by_ticket.get(ticket_id)) is not None
                and current_step < claim.claimed_step
            )
            for ticket_id in outstanding
        ):
            raise DemandReservoirStateError("reservoir cannot close before outstanding demand")
        self._queues.clear()
        retired = []
        for ticket_id in outstanding:
            ticket = self._tickets[ticket_id]
            deadline = ticket.departure_deadline_step
            if deadline is not None and current_step >= deadline:
                retired.append(
                    self._retire_unpublished(
                        ticket,
                        deadline,
                        DemandTicketState.NOT_ALIGHTED,
                        "train_alighting_capacity_insufficient",
                    )
                )
                self._expired_train_refs.add(str(ticket.source_ref))
                continue
            retired.append(
                self._retire_unpublished(
                    ticket,
                    current_step,
                    DemandTicketState.RIGHT_CENSORED,
                    "lifecycle_right_censored",
                )
            )
        self._closed = True
        return tuple(retired)

    def state_of(self, ticket: DemandTicket) -> DemandTicketState:
        return self._states[ticket.sequence_id]

    @property
    def deferrals(self) -> tuple[DemandDeferral, ...]:
        return tuple(self._deferrals)

    @property
    def residences(self) -> tuple[DemandResidence, ...]:
        return tuple(self._residences)

    def residences_for(
        self,
        source_kind: DemandSourceKind,
        source_ref: str | None = None,
    ) -> tuple[DemandResidence, ...]:
        boundary = (source_kind, source_ref)
        return tuple(item for item in self._residences if item.ticket.boundary == boundary)

    def pending_tickets(
        self,
        source_kind: DemandSourceKind | None = None,
        *,
        source_ref: str | None = None,
        match_source_ref: bool = False,
    ) -> tuple[DemandTicket, ...]:
        """Return immutable pending ownership, optionally scoped to one boundary."""

        ticket_ids = sorted(ticket_id for queue in self._queues.values() for ticket_id in queue)
        tickets = tuple(self._tickets[ticket_id] for ticket_id in ticket_ids)
        if source_kind is not None:
            tickets = tuple(ticket for ticket in tickets if ticket.source_kind == source_kind)
        if match_source_ref:
            tickets = tuple(ticket for ticket in tickets if ticket.source_ref == source_ref)
        return tickets

    def pending_groups(self, source_kind: DemandSourceKind | None = None) -> int:
        return len(self.pending_tickets(source_kind))

    def pending_persons(self, source_kind: DemandSourceKind | None = None) -> int:
        return sum(ticket.group_size for ticket in self.pending_tickets(source_kind))

    def _validate_configuration(
        self,
        scheduled_step: int,
        intent: str,
        group_size: int,
        source_kind: DemandSourceKind,
        source_ref: str | None,
        departure_deadline_step: int | None,
    ) -> None:
        _require_step(scheduled_step, "scheduled step")
        if not isinstance(intent, str) or not intent.strip():
            raise InvalidDemandConfiguration("intent must be a non-empty string")
        if not isinstance(group_size, int) or isinstance(group_size, bool) or group_size <= 0:
            raise InvalidDemandConfiguration("group_size must be a positive integer")
        if not isinstance(source_kind, DemandSourceKind):
            raise InvalidDemandConfiguration("source_kind must be typed")
        if source_ref is not None and (not isinstance(source_ref, str) or not source_ref.strip()):
            raise InvalidDemandConfiguration("source_ref must be a non-empty string when present")
        if source_kind == DemandSourceKind.ENTRY:
            if departure_deadline_step is not None:
                raise InvalidDemandConfiguration("entry demand cannot have a departure deadline")
            return
        if source_ref is None or departure_deadline_step is None:
            raise InvalidDemandConfiguration(
                "train alighting demand requires an arrival ref and departure deadline"
            )
        deadline = _require_step(departure_deadline_step, "departure deadline")
        if deadline <= scheduled_step:
            raise InvalidDemandConfiguration("departure deadline must follow the scheduled step")
        if source_ref in self._expired_train_refs:
            raise InvalidDemandConfiguration("train arrival reference has already departed")
        known_deadline = self._train_deadline_by_ref.setdefault(source_ref, deadline)
        if known_deadline != deadline:
            raise InvalidDemandConfiguration("one train arrival cannot have multiple deadlines")

    def _require_active_claim(self, claim: DemandClaim) -> None:
        active = self._active_claim_by_ticket.get(claim.ticket.sequence_id)
        if (
            active != claim
            or self._states.get(claim.ticket.sequence_id) != DemandTicketState.CLAIMED
        ):
            raise DemandReservoirStateError("claim is stale or no longer active")

    @staticmethod
    def _require_not_before_claim(claim: DemandClaim, step: int) -> None:
        if step < claim.claimed_step:
            raise DemandReservoirStateError("claim cannot be resolved before it was acquired")

    def _pop_claimed_head(self, claim: DemandClaim) -> None:
        queue = self._queues[claim.ticket.boundary]
        if not queue or queue[0] != claim.ticket.sequence_id:
            raise DemandReservoirStateError("claim no longer owns its FIFO head")
        queue.popleft()
        if not queue:
            self._queues.pop(claim.ticket.boundary, None)
        self._active_claim_by_ticket.pop(claim.ticket.sequence_id)

    def _retire_unpublished(
        self,
        ticket: DemandTicket,
        step: int,
        outcome: DemandTicketState,
        reason: str,
    ) -> DemandResidence:
        self._active_claim_by_ticket.pop(ticket.sequence_id, None)
        return self._record_residence(ticket, step, outcome, reason)

    def _record_residence(
        self,
        ticket: DemandTicket,
        step: int,
        outcome: DemandTicketState,
        reason: str,
        passenger_id: Hashable | None = None,
    ) -> DemandResidence:
        residence = DemandResidence(ticket, step, outcome, reason, passenger_id)
        self._states[ticket.sequence_id] = outcome
        self._residences.append(residence)
        return residence

    def _require_open(self) -> None:
        if self._closed:
            raise DemandReservoirStateError("external demand reservoir is closed")


def _require_step(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise InvalidDemandConfiguration(f"{label} must be a non-negative integer")
    return value


__all__ = [
    "DemandClaim",
    "DemandDeferral",
    "DemandResidence",
    "DemandReservoirStateError",
    "DemandSourceKind",
    "DemandTicket",
    "DemandTicketState",
    "ExternalDemandReservoir",
    "InvalidDemandConfiguration",
    "TemporaryDemandBlockReason",
]
