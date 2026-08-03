from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..goals.graph import JourneyGraph
from .serialization import journey_graph_from_mapping, journey_graph_to_dict
from .intents import station_exit_journey_graph, station_transfer_journey_graph
from .boarding import station_entry_to_boarding_journey_graph
from ..passengers import AgentIntent


@dataclass(frozen=True)
class JourneyGraphCatalog:
    entries: tuple[tuple[str, JourneyGraph], ...]
    version: int = 1
    _by_intent: dict[str, JourneyGraph] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("journey catalog version must be positive")
        by_intent = dict(self.entries)
        if not by_intent:
            raise ValueError("journey catalog requires at least one intent mapping")
        if len(by_intent) != len(self.entries):
            raise ValueError("journey catalog contains duplicate intents")
        object.__setattr__(self, "_by_intent", by_intent)

    def graph_for_intent(self, intent: str | AgentIntent) -> JourneyGraph | None:
        intent_value = intent.value if isinstance(intent, AgentIntent) else str(intent)
        return self._by_intent.get(intent_value)

    def require_intents(self, intents: tuple[str | AgentIntent, ...]) -> None:
        missing = [
            intent.value if isinstance(intent, AgentIntent) else str(intent)
            for intent in intents
            if self.graph_for_intent(intent) is None
        ]
        if missing:
            raise ValueError(
                "journey graph catalog is missing required intents: "
                + ", ".join(sorted(missing))
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "journeys": {
                intent: journey_graph_to_dict(graph) for intent, graph in self.entries
            },
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> JourneyGraphCatalog:
        journeys = payload.get("journeys")
        if not isinstance(journeys, Mapping):
            raise ValueError("journey catalog requires a 'journeys' mapping")
        return cls(
            version=int(payload.get("version", 1)),
            entries=tuple(
                (str(intent), journey_graph_from_mapping(graph_payload))
                for intent, graph_payload in journeys.items()
                if isinstance(graph_payload, Mapping)
            ),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> JourneyGraphCatalog:
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load journey graph catalog {source}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("journey graph catalog root must be an object")
        return cls.from_mapping(payload)


def default_journey_graph_catalog() -> JourneyGraphCatalog:
    return JourneyGraphCatalog(
        entries=(
            (
                AgentIntent.ENTER_AND_BOARD.value,
                station_entry_to_boarding_journey_graph(),
            ),
            (AgentIntent.EXIT_STATION.value, station_exit_journey_graph()),
            (
                AgentIntent.EVACUATE_STATION.value,
                station_exit_journey_graph(graph_id="station_evacuation"),
            ),
            (AgentIntent.TRANSFER.value, station_transfer_journey_graph()),
        )
    )


def load_journey_graph_catalog(path: str | Path | None) -> JourneyGraphCatalog:
    if path is None:
        return default_journey_graph_catalog()
    return JourneyGraphCatalog.from_json_file(path)
