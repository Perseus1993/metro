"""Compatibility module; import from ``metro_station.adapters.simulation.design.geometry`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station.adapters.simulation.design.geometry")
_sys.modules[__name__] = _target
