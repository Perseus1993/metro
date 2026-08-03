"""Concrete routing-plugin adapters."""

from .baseline import BASELINE_PLUGIN_ID, BaselineEvacuationRouter
from .contract_suite import RoutingContractReport, run_routing_contract_suite, validate_plugin_file
from .process_host import RoutingPluginProcessHost
from .registry import AlgorithmRegistration, RoutingAlgorithmRegistry

__all__ = [
    "BASELINE_PLUGIN_ID",
    "BaselineEvacuationRouter",
    "RoutingContractReport",
    "RoutingAlgorithmRegistry",
    "AlgorithmRegistration",
    "RoutingPluginProcessHost",
    "run_routing_contract_suite",
    "validate_plugin_file",
]
