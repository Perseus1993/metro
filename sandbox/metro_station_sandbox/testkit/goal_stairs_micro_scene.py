"""Compatibility module; import from ``metro_station_testkit.goal_stairs_micro_scene`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station_testkit.goal_stairs_micro_scene")
_sys.modules[__name__] = _target
