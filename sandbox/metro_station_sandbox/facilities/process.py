"""Compatibility module; import from ``metro_station.adapters.simulation.facilities.process`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station.adapters.simulation.facilities.process")
_sys.modules[__name__] = _target
