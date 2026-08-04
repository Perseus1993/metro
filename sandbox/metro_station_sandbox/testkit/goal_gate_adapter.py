"""Compatibility module; import from ``metro_station_testkit.goal_gate_adapter`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station_testkit.goal_gate_adapter")
_sys.modules[__name__] = _target
