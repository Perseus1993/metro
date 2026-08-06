from __future__ import annotations

from dataclasses import asdict, dataclass, field


FAIL_CAPACITY = "FAIL_CAPACITY"
TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT = "train_alighting_capacity_insufficient"

MANIFEST_OPEN = "open"
MANIFEST_DEPARTED = "departed"
MANIFEST_FAILED = "failed"


class TrainExchangeLifecycleError(RuntimeError):
    """Raised when a terminal train-exchange manifest is mutated again."""


@dataclass(frozen=True, order=True)
class TrainRunId:
    platform_id: str
    arrival_sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.platform_id, str) or not self.platform_id.strip():
            raise ValueError("platform_id must not be blank")
        _require_int_at_least("arrival_sequence", self.arrival_sequence, 1)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TrainExchangeCloseResult:
    train_run_id: TrainRunId
    status: str
    failure_code: str | None
    planned_alight_persons: int
    released_alight_persons: int
    not_alighted_persons: int
    release_complete_step: int | None
    actual_departure_step: int | None
    boarded_persons: int
    departure_load_persons: int
    capacity_persons: int
    departure_policy: str

    @property
    def departed(self) -> bool:
        return self.status == MANIFEST_DEPARTED

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["train_run_id"] = self.train_run_id.as_dict()
        return payload


@dataclass
class TrainExchangeManifest:
    """Physical exchange ledger for one train arrival at one platform.

    Under ``FAIL_CAPACITY``, closing is an atomic terminal decision. A fully
    released manifest departs; an incomplete manifest returns a structured
    failure and never publishes a successful departure.
    """

    train_run_id: TrainRunId
    arrival_step: int
    scheduled_close_step: int
    capacity_persons: int
    inbound_load_persons: int
    planned_alight_persons: int
    through_load_persons: int
    departure_policy: str = FAIL_CAPACITY
    released_alight_persons: int = field(default=0, init=False)
    not_alighted_persons: int = field(init=False)
    release_complete_step: int | None = field(default=None, init=False)
    actual_departure_step: int | None = field(default=None, init=False)
    boarded_persons: int = field(default=0, init=False)
    departure_load_persons: int = field(init=False)
    status: str = field(default=MANIFEST_OPEN, init=False)
    failure_code: str | None = field(default=None, init=False)
    _last_release_step: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _require_int_at_least("arrival_step", self.arrival_step, 0)
        _require_int_at_least("scheduled_close_step", self.scheduled_close_step, 0)
        if self.scheduled_close_step < self.arrival_step:
            raise ValueError("scheduled_close_step must be at or after arrival_step")
        _require_int_at_least("capacity_persons", self.capacity_persons, 1)
        _require_int_at_least("inbound_load_persons", self.inbound_load_persons, 0)
        _require_int_at_least("planned_alight_persons", self.planned_alight_persons, 0)
        _require_int_at_least("through_load_persons", self.through_load_persons, 0)
        if self.planned_alight_persons > self.inbound_load_persons:
            raise ValueError("planned_alight_persons must not exceed inbound_load_persons")
        if self.inbound_load_persons > self.capacity_persons:
            raise ValueError("inbound_load_persons must not exceed capacity_persons")
        expected_through = self.inbound_load_persons - self.planned_alight_persons
        if self.through_load_persons != expected_through:
            raise ValueError(
                "through_load_persons must equal "
                "inbound_load_persons - planned_alight_persons"
            )
        if self.departure_policy != FAIL_CAPACITY:
            raise ValueError(f"departure_policy must be {FAIL_CAPACITY!r}")

        self.not_alighted_persons = self.planned_alight_persons
        self.departure_load_persons = self.through_load_persons
        if self.planned_alight_persons == 0:
            self.release_complete_step = self.arrival_step

    @property
    def pending_alight_persons(self) -> int:
        return self.not_alighted_persons

    def release_alighting(self, persons: int, *, at_step: int) -> None:
        """Release one person count into certified station-side ownership."""

        self._ensure_open("release alighting")
        _require_int_at_least("persons", persons, 1)
        self._validate_exchange_step("at_step", at_step)
        if at_step > self.scheduled_close_step:
            raise ValueError("alighting release must not occur after scheduled_close_step")
        if self._last_release_step is not None and at_step < self._last_release_step:
            raise ValueError("alighting release steps must be non-decreasing")
        if self.released_alight_persons + persons > self.planned_alight_persons:
            raise ValueError("alighting release must not exceed planned_alight_persons")

        self.released_alight_persons += persons
        self.not_alighted_persons = self.planned_alight_persons - self.released_alight_persons
        self._last_release_step = at_step
        if self.not_alighted_persons == 0:
            self.release_complete_step = at_step

    def release_alighting_group(self, group_persons: int, *, at_step: int) -> None:
        """Release an indivisible passenger group, expressed in persons."""

        self.release_alighting(group_persons, at_step=at_step)

    def record_boarding(self, persons: int) -> None:
        self._ensure_open("record boarding")
        _require_int_at_least("persons", persons, 1)
        proposed_onboard_load = (
            self.inbound_load_persons
            - self.released_alight_persons
            + self.boarded_persons
            + persons
        )
        if proposed_onboard_load > self.capacity_persons:
            raise ValueError("current onboard load must not exceed capacity_persons")
        self.boarded_persons += persons
        self.departure_load_persons = self.through_load_persons + self.boarded_persons

    def close(self, *, actual_departure_step: int) -> TrainExchangeCloseResult:
        """Close the exchange and either depart or return a structured capacity failure."""

        self._ensure_open("close")
        self._validate_exchange_step("actual_departure_step", actual_departure_step)
        if actual_departure_step < self.scheduled_close_step:
            raise ValueError("actual_departure_step must be at or after scheduled_close_step")

        self.not_alighted_persons = (
            self.planned_alight_persons - self.released_alight_persons
        )
        self.departure_load_persons = self.through_load_persons + self.boarded_persons
        if self.departure_load_persons > self.capacity_persons:
            raise ValueError("departure_load_persons must not exceed capacity_persons")

        if self.not_alighted_persons > 0:
            self.status = MANIFEST_FAILED
            self.failure_code = TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT
            self.actual_departure_step = None
            return self._close_result()

        if self.release_complete_step is None:
            raise RuntimeError("complete alighting manifest has no release_complete_step")
        if self.release_complete_step > actual_departure_step:
            raise ValueError("release_complete_step must be at or before actual_departure_step")

        self.actual_departure_step = actual_departure_step
        self.status = MANIFEST_DEPARTED
        self.failure_code = None
        return self._close_result()

    def depart(self, *, actual_departure_step: int) -> TrainExchangeCloseResult:
        """Alias for the atomic close-and-depart operation."""

        return self.close(actual_departure_step=actual_departure_step)

    def _close_result(self) -> TrainExchangeCloseResult:
        return TrainExchangeCloseResult(
            train_run_id=self.train_run_id,
            status=self.status,
            failure_code=self.failure_code,
            planned_alight_persons=self.planned_alight_persons,
            released_alight_persons=self.released_alight_persons,
            not_alighted_persons=self.not_alighted_persons,
            release_complete_step=self.release_complete_step,
            actual_departure_step=self.actual_departure_step,
            boarded_persons=self.boarded_persons,
            departure_load_persons=self.departure_load_persons,
            capacity_persons=self.capacity_persons,
            departure_policy=self.departure_policy,
        )

    def _ensure_open(self, operation: str) -> None:
        if self.status != MANIFEST_OPEN:
            raise TrainExchangeLifecycleError(
                f"cannot {operation}: train exchange manifest is already {self.status}"
            )

    def _validate_exchange_step(self, name: str, step: int) -> None:
        _require_int_at_least(name, step, 0)
        if step < self.arrival_step:
            raise ValueError(f"{name} must be at or after arrival_step")


def _require_int_at_least(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}; got {value!r}")
