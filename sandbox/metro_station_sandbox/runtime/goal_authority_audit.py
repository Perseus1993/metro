"""Compatibility module; import from ``metro_station.adapters.simulation.runtime.goal_authority_audit`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station.adapters.simulation.runtime.goal_authority_audit")
_sys.modules[__name__] = _target
