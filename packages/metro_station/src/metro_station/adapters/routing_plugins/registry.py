"""Reviewed-local registry and compatibility preflight for routing algorithms."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metro_station.application.comparisons import (
    ALGORITHM_ROLES,
    AlgorithmSelection,
    ExperimentPlan,
)
from metro_station.application.routing_plugins import (
    AlgorithmManifest,
    EvacuationRoutingPort,
    manifest_from_json,
)

from .baseline import BaselineEvacuationRouter
from .process_host import RoutingPluginProcessHost


AlgorithmFactory = Callable[[], EvacuationRoutingPort]


@dataclass(frozen=True)
class AlgorithmRegistration:
    registration_id: str
    manifest: AlgorithmManifest
    factory: AlgorithmFactory
    source: str

    def catalog_payload(self) -> dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "source": self.source,
            "manifest": self.manifest.as_dict(),
        }


class RoutingAlgorithmRegistry:
    """Create only algorithms explicitly registered by the local operator."""

    def __init__(self) -> None:
        self._registrations: dict[str, AlgorithmRegistration] = {}

    @classmethod
    def with_baseline(cls) -> RoutingAlgorithmRegistry:
        registry = cls()
        router = BaselineEvacuationRouter()
        registration_id = _registration_id("builtin", router.manifest)
        registry._add(
            AlgorithmRegistration(
                registration_id,
                router.manifest,
                BaselineEvacuationRouter,
                "builtin",
            )
        )
        return registry

    def register_manifest_file(
        self,
        manifest_path: str | Path,
        *,
        timeout_seconds: float = 2.0,
        run_timeout_seconds: float = 60.0,
    ) -> AlgorithmRegistration:
        path = Path(manifest_path).resolve()
        manifest = manifest_from_json(path.read_text(encoding="utf-8"))
        registration_id = _registration_id("local", manifest)

        def factory() -> EvacuationRoutingPort:
            return RoutingPluginProcessHost(
                manifest,
                working_directory=path.parent,
                timeout_seconds=timeout_seconds,
                run_timeout_seconds=run_timeout_seconds,
            )

        registration = AlgorithmRegistration(registration_id, manifest, factory, str(path))
        self._add(registration)
        return registration

    def catalog(self) -> list[dict[str, Any]]:
        return [
            registration.catalog_payload()
            for registration in sorted(
                self._registrations.values(),
                key=lambda item: (item.source != "builtin", item.registration_id),
            )
        ]

    def preflight(self, payload: Mapping[str, Any]) -> AlgorithmSelection:
        registration_id = str(payload.get("registration_id", ""))
        registration = self._registrations.get(registration_id)
        if registration is None:
            raise ValueError(f"routing algorithm is not registered: {registration_id!r}")
        claimed = payload.get("manifest")
        if claimed is not None:
            if not isinstance(claimed, Mapping):
                raise ValueError("algorithm manifest must be an object")
            if AlgorithmManifest.from_dict(claimed) != registration.manifest:
                raise ValueError("registered algorithm manifest/version does not match experiment")
        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError("algorithm parameters must be an object")
        return AlgorithmSelection(registration_id, registration.manifest, dict(parameters))

    @contextmanager
    def open_plan(
        self,
        plan: ExperimentPlan,
    ) -> Iterator[dict[str, EvacuationRoutingPort]]:
        opened: dict[str, EvacuationRoutingPort] = {}
        try:
            for role, selection in zip(ALGORITHM_ROLES, plan.algorithms, strict=True):
                verified = self.preflight(selection.as_dict())
                registration = self._registrations[verified.registration_id]
                opened[role] = registration.factory()
            yield opened
        finally:
            for algorithm in opened.values():
                close = getattr(algorithm, "close", None)
                if callable(close):
                    close()

    def _add(self, registration: AlgorithmRegistration) -> None:
        existing = self._registrations.get(registration.registration_id)
        if existing is not None and existing.manifest != registration.manifest:
            raise ValueError(f"algorithm registration conflicts: {registration.registration_id}")
        self._registrations[registration.registration_id] = registration


def _registration_id(source: str, manifest: AlgorithmManifest) -> str:
    return f"{source}:{manifest.plugin_id}@{manifest.plugin_version}"
