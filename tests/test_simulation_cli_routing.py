from __future__ import annotations

import pytest

from metro_station.adapters.routing_plugins import BaselineEvacuationRouter
from metro_station.adapters.simulation import cli


def test_cli_defaults_to_versioned_routing_baseline() -> None:
    args = cli.build_parser().parse_args([])

    with cli.open_routing_algorithm(args) as (algorithm, parameters):
        assert isinstance(algorithm, BaselineEvacuationRouter)
        assert algorithm.manifest.plugin_id == "metro.shortest_path"
        assert parameters == {}


def test_cli_rejects_non_object_routing_parameters() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--routing-parameters-json", "[]"])
