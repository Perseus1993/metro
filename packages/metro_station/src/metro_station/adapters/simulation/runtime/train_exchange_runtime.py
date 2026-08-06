from __future__ import annotations

from ..agents.transit import TrainAgent
from .external_demand_reservoir import DemandSourceKind
from .train_exchange_manifest import (
    MANIFEST_FAILED,
    TrainExchangeManifest,
    TrainRunId,
)


class TrainExchangeRuntimeMixin:
    """Bind nominal alighting demand and departure to one finite train run."""

    def sync_train_exchange_manifests(self) -> None:
        newly_arrived = [
            train
            for train in self.trains
            if train.is_boarding and self._train_run_ref(train) not in self.train_exchange_manifests
        ]
        if not newly_arrived:
            return
        newly_arrived.sort(key=lambda train: (str(train.platform_id), int(train.unique_id)))
        total_groups = self._planned_alighting_groups_at(newly_arrived[0].arrival_step)
        for train, groups in zip(
            newly_arrived,
            self._split_count(total_groups, len(newly_arrived)),
            strict=True,
        ):
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
        boarded_delta = int(train.current_load_persons) - int(manifest.boarded_persons)
        if boarded_delta > 0:
            manifest.record_boarding(boarded_delta)
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
                    "departure_policy": manifest.departure_policy,
                    "dwell_extension_steps": 0,
                    "run_ref": run_ref,
                }
            )
        return rows

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
