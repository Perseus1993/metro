from __future__ import annotations

from ..agents.transit import TrainAgent
from .external_demand_reservoir import DemandSourceKind
from .train_exchange_manifest import (
    MANIFEST_FAILED,
    TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT,
    TrainExchangeManifest,
    TrainRunId,
)


class TrainExchangeRuntimeMixin:
    """Bind nominal alighting demand and departure to one finite train run."""

    def sync_train_exchange_manifests(self) -> bool:
        newly_arrived = [
            train
            for train in self.trains
            if train.is_boarding and self._train_run_ref(train) not in self.train_exchange_manifests
        ]
        if not newly_arrived:
            return True
        newly_arrived.sort(key=lambda train: (str(train.platform_id), int(train.unique_id)))
        total_groups = self._planned_alighting_groups_at(newly_arrived[0].arrival_step)
        allocations = list(
            zip(
                newly_arrived,
                self._split_count(total_groups, len(newly_arrived)),
                strict=True,
            )
        )
        for train, groups in allocations:
            persons = int(groups) * int(self.scenario.group_size)
            capacity = int(self.train_capacity_for_platform(train.platform_id))
            if persons > capacity:
                self._record_alighting_capacity_failure(
                    train,
                    planned_alight_persons=persons,
                    capacity_persons=capacity,
                )
                return False
        for train, groups in allocations:
            persons = int(groups) * int(self.scenario.group_size)
            run_ref = self._train_run_ref(train)
            self.train_exchange_manifests[run_ref] = TrainExchangeManifest(
                train_run_id=TrainRunId(str(train.platform_id), int(train.arrival_sequence)),
                arrival_step=int(train.arrival_step),
                scheduled_close_step=int(train.close_step),
                capacity_persons=int(self.train_capacity_for_platform(train.platform_id)),
                inbound_load_persons=persons,
                planned_alight_persons=persons,
                through_load_persons=0,
            )
        return True

    def train_exchange_current_onboard_persons(self, train: TrainAgent) -> int | None:
        manifest = self._active_train_exchange_manifest(train)
        return None if manifest is None else int(manifest.current_onboard_persons)

    def train_exchange_reserved_boarding_persons(self, train: TrainAgent) -> int | None:
        manifest = self._active_train_exchange_manifest(train)
        return None if manifest is None else int(manifest.reserved_boarding_persons)

    def train_boarding_capacity_remaining(self, train: TrainAgent) -> int | None:
        manifest = self._active_train_exchange_manifest(train)
        if manifest is not None:
            return int(manifest.capacity_remaining)
        if int(train.arrival_sequence) == 0:
            return None
        return 0

    def reserve_train_boarding_capacity(self, train: TrainAgent, persons: int) -> None:
        manifest = self._active_train_exchange_manifest(train)
        if manifest is None:
            self._reserve_legacy_test_boarding(train, persons)
            return
        manifest.reserve_boarding(persons)

    def commit_train_boarding(self, train: TrainAgent, persons: int) -> None:
        manifest = self._active_train_exchange_manifest(train)
        if manifest is None:
            self._commit_legacy_test_boarding(train, persons)
            return
        manifest.commit_boarding(persons)

    def close_train_exchange_for_departure(self, train: TrainAgent, *, step: int) -> bool:
        """Return true only when the train may publish a successful departure."""

        run_ref = self._train_run_ref(train)
        manifest = self.train_exchange_manifests.get(run_ref)
        if manifest is None:
            if int(train.arrival_sequence) == 0:
                # Compatibility for isolated door-crossing unit tests that
                # manually berth a train without publishing an arrival event.
                # Runtime arrivals start at sequence 1 and remain fail-closed.
                return True
            raise RuntimeError(f"train exchange manifest missing for {run_ref}")
        pending = self.external_demand_reservoir.pending_tickets(
            DemandSourceKind.TRAIN_ALIGHTING,
            source_ref=run_ref,
            match_source_ref=True,
        )
        if pending:
            self.external_demand_reservoir.expire_train_arrival(run_ref, step=step)
        result = manifest.close(actual_departure_step=step)
        self.train_exchange_results.append(result)
        if result.status == MANIFEST_FAILED:
            self.run_outcome_code = str(result.failure_code)
            self.running = False
            self.audit.record(
                str(result.failure_code),
                source="train_exchange_manifest",
                severity="error",
                step=step,
                context=result.as_dict(),
            )
            return False
        return True

    def train_exchange_result_rows(self) -> list[dict[str, object]]:
        rows = []
        for result in self.train_exchange_results:
            row = result.as_dict()
            run_ref = (
                f"{result.train_run_id.platform_id}:"
                f"{int(result.train_run_id.arrival_sequence)}"
            )
            manifest = self.train_exchange_manifests[run_ref]
            row.update(
                {
                    "arrival_step": manifest.arrival_step,
                    "scheduled_close_step": manifest.scheduled_close_step,
                    "inbound_load_persons": manifest.inbound_load_persons,
                    "through_load_persons": manifest.through_load_persons,
                    "reserved_boarding_persons": manifest.reserved_boarding_persons,
                    "current_onboard_persons": manifest.current_onboard_persons,
                    "run_ref": run_ref,
                    "dwell_extension_steps": 0,
                }
            )
            rows.append(row)
        closed_refs = {
            (
                str(row["train_run_id"]["platform_id"]),
                int(row["train_run_id"]["arrival_sequence"]),
            )
            for row in rows
        }
        for run_ref, manifest in sorted(self.train_exchange_manifests.items()):
            run_id = manifest.train_run_id.as_dict()
            run_key = (str(run_id["platform_id"]), int(run_id["arrival_sequence"]))
            if run_key in closed_refs:
                continue
            rows.append(
                {
                    "train_run_id": run_id,
                    "arrival_step": manifest.arrival_step,
                    "scheduled_close_step": manifest.scheduled_close_step,
                    "departure_status": manifest.status,
                    "failure_code": manifest.failure_code,
                    "planned_alight_persons": manifest.planned_alight_persons,
                    "released_alight_persons": manifest.released_alight_persons,
                    "not_alighted_persons": manifest.not_alighted_persons,
                    "alighting_release_complete_step": manifest.release_complete_step,
                    "actual_departure_step": manifest.actual_departure_step,
                    "capacity_persons": manifest.capacity_persons,
                    "inbound_load_persons": manifest.inbound_load_persons,
                    "through_load_persons": manifest.through_load_persons,
                    "boarded_persons": manifest.boarded_persons,
                    "reserved_boarding_persons": manifest.reserved_boarding_persons,
                    "current_onboard_persons": manifest.current_onboard_persons,
                    "departure_load_persons": manifest.departure_load_persons,
                    "departure_policy": manifest.departure_policy,
                    "dwell_extension_steps": 0,
                    "run_ref": run_ref,
                }
            )
        return rows

    def _record_alighting_capacity_failure(
        self,
        train: TrainAgent,
        *,
        planned_alight_persons: int,
        capacity_persons: int,
    ) -> None:
        run_ref = self._train_run_ref(train)
        failure = {
            "train_run_id": {
                "platform_id": str(train.platform_id),
                "arrival_sequence": int(train.arrival_sequence),
            },
            "run_ref": run_ref,
            "arrival_step": int(train.arrival_step),
            "scheduled_close_step": int(train.close_step),
            "departure_status": MANIFEST_FAILED,
            "failure_code": TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT,
            "capacity_persons": int(capacity_persons),
            "inbound_load_persons": int(planned_alight_persons),
            "planned_alight_persons": int(planned_alight_persons),
            "released_alight_persons": 0,
            "not_alighted_persons": int(planned_alight_persons),
            "actual_departure_step": None,
            "departure_policy": "FAIL_CAPACITY",
            "dwell_extension_steps": 0,
        }
        self.run_outcome_code = TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT
        self.running = False
        self._record_unavailable_alighting_manifest_remainder(
            int(planned_alight_persons) // int(self.scenario.group_size)
        )
        self.unbound_not_alighted_persons += int(planned_alight_persons)
        self.failed_nominal_alighting_arrivals.add(int(train.arrival_step))
        self.train_exchange_failure_rows.append(failure)
        self.audit.record(
            TRAIN_ALIGHTING_CAPACITY_INSUFFICIENT,
            source="train_exchange_manifest",
            severity="error",
            step=int(self.step_index),
            context=failure,
        )

    def _active_train_exchange_manifest(
        self,
        train: TrainAgent,
    ) -> TrainExchangeManifest | None:
        if not train.is_boarding:
            return None
        return self.train_exchange_manifests.get(self._train_run_ref(train))

    def _reserve_legacy_test_boarding(self, train: TrainAgent, persons: int) -> None:
        if int(train.arrival_sequence) != 0:
            raise RuntimeError(
                f"train exchange manifest missing for {self._train_run_ref(train)}"
            )
        available = max(
            0,
            int(self.train_capacity_for_platform(train.platform_id))
            - int(train._legacy_current_load_persons)
            - int(train._legacy_reserved_boarding_persons),
        )
        if int(persons) > available:
            raise ValueError("current onboard load must not exceed capacity_persons")
        train._legacy_reserved_boarding_persons += int(persons)

    def _commit_legacy_test_boarding(self, train: TrainAgent, persons: int) -> None:
        if int(train.arrival_sequence) != 0:
            raise RuntimeError(
                f"train exchange manifest missing for {self._train_run_ref(train)}"
            )
        if int(persons) > int(train._legacy_reserved_boarding_persons):
            raise RuntimeError("legacy boarding commit exceeds its reservation")
        train._legacy_reserved_boarding_persons -= int(persons)
        train._legacy_current_load_persons += int(persons)

    def _planned_alighting_groups_at(self, arrival_step: int) -> int:
        return next(
            (
                int(plan.planned_groups)
                for plan in self.planned_train_alightings
                if int(plan.arrival_step) == int(arrival_step)
            ),
            0,
        )

    @staticmethod
    def _train_run_ref(train: TrainAgent) -> str:
        return f"{train.platform_id}:{int(train.arrival_sequence)}"


__all__ = ["TrainExchangeRuntimeMixin"]
