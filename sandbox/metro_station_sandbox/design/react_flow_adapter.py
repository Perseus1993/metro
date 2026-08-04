"""Compatibility module; import from ``metro_station.adapters.simulation.design.react_flow_adapter`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station.adapters.simulation.design.react_flow_adapter")
_sys.modules[__name__] = _target
