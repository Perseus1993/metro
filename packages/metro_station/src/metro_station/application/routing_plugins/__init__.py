"""Public application contracts for evacuation-routing plugins."""

from .contracts import (
    EVACUATION_ROUTING_SCHEMA_VERSION,
    ROUTE_NOT_FOUND,
    ROUTE_SUCCESS,
    EvacuationRoutingRequest,
    EvacuationRoutingResponse,
    PassengerGroupFacts,
    RoutingDiagnostics,
)
from .execution import (
    ROUTING_DECISION_LOG_SCHEMA_VERSION,
    EvacuationRoutingPort,
    RoutingDecisionLog,
    RoutingInvocationResult,
)
from .manifest import (
    ALGORITHM_PLUGIN_SCHEMA_VERSION,
    EVACUATION_ROUTING_API_VERSION,
    EVACUATION_ROUTING_KIND,
    AlgorithmManifest,
)
from .serialization import (
    manifest_from_json,
    manifest_to_json,
    routing_request_from_json,
    routing_request_to_json,
    routing_response_from_json,
    routing_response_to_json,
)
from .topology import (
    EVACUATION_TOPOLOGY_SCHEMA_VERSION,
    RoutingEdge,
    RoutingNode,
    RoutingTopology,
)
from .validation import validate_routing_response

__all__ = [
    "ALGORITHM_PLUGIN_SCHEMA_VERSION",
    "EVACUATION_ROUTING_API_VERSION",
    "EVACUATION_ROUTING_KIND",
    "EVACUATION_ROUTING_SCHEMA_VERSION",
    "EVACUATION_TOPOLOGY_SCHEMA_VERSION",
    "ROUTE_NOT_FOUND",
    "ROUTE_SUCCESS",
    "ROUTING_DECISION_LOG_SCHEMA_VERSION",
    "AlgorithmManifest",
    "EvacuationRoutingPort",
    "EvacuationRoutingRequest",
    "EvacuationRoutingResponse",
    "PassengerGroupFacts",
    "RoutingDecisionLog",
    "RoutingDiagnostics",
    "RoutingEdge",
    "RoutingInvocationResult",
    "RoutingNode",
    "RoutingTopology",
    "manifest_from_json",
    "manifest_to_json",
    "routing_request_from_json",
    "routing_request_to_json",
    "routing_response_from_json",
    "routing_response_to_json",
    "validate_routing_response",
]
