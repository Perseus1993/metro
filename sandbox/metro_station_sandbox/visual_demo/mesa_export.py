"""Compatibility module; import from ``metro_station_visualizer.mesa_export`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_station_visualizer.mesa_export")
_sys.modules[__name__] = _target
