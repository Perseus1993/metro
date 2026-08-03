from __future__ import annotations

from ...domain.journeys.catalog import JourneyGraphCatalog
from ...domain.journeys.intents import journey_graph_for_facility_chain
from ...domain.passengers import AgentIntent, FacilityStage
from ...domain.station import JourneyTopologyPort


_GRAPH_IDS = {
    AgentIntent.ENTER_AND_BOARD: "station_entry_to_boarding",
    AgentIntent.EXIT_STATION: "station_exit",
    AgentIntent.EVACUATE_STATION: "station_evacuation",
    AgentIntent.TRANSFER: "station_transfer",
}


def compile_journey_graph_catalog(station_graph: JourneyTopologyPort) -> JourneyGraphCatalog:
    entries = []
    for intent, graph_id in _GRAPH_IDS.items():
        facility_chain = _facility_chain(intent, station_graph)
        terminal_region_id = (
            "safe_zone"
            if intent == AgentIntent.EVACUATE_STATION
            else "station_exit"
            if intent == AgentIntent.EXIT_STATION
            else None
        )
        entries.append(
            (
                intent.value,
                journey_graph_for_facility_chain(
                    graph_id=graph_id,
                    facility_chain=facility_chain,
                    terminal_region_id=terminal_region_id,
                ),
            )
        )
    return JourneyGraphCatalog(entries=tuple(entries))


def _facility_chain(
    intent: AgentIntent,
    station_graph: JourneyTopologyPort,
) -> tuple[str, ...]:
    vertical_count = station_graph.vertical_transfer_count_for_intent(intent.value)
    vertical = (FacilityStage.VERTICAL_TRANSFER.value,) * vertical_count
    if intent == AgentIntent.ENTER_AND_BOARD:
        return (
            FacilityStage.ENTRY_GATE.value,
            *vertical,
            FacilityStage.BOARDING_DOOR.value,
        )
    if intent == AgentIntent.TRANSFER:
        return (*vertical, FacilityStage.BOARDING_DOOR.value)
    return (*vertical, FacilityStage.EXIT_GATE.value)
