"""Compatibility module; import from ``metro_data_warehouse.amap_network`` instead."""

import sys as _sys
from importlib import import_module as _import_module

_target = _import_module("metro_data_warehouse.amap_network")
_sys.modules[__name__] = _target
