"""Compatibility module; import from ``metro_station_visualizer.record_visual_demo`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station_visualizer.record_visual_demo")
_sys.modules[__name__] = _target
