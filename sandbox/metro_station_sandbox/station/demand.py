"""Compatibility module; import from ``metro_station.adapters.simulation.station.demand`` instead."""

from importlib import import_module as _import_module
import sys as _sys


_target = _import_module("metro_station.adapters.simulation.station.demand")
_sys.modules[__name__] = _target
