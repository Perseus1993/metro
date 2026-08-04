"""Compatibility package; import from ``metro_station.adapters.simulation.presets`` instead."""

from importlib import import_module as _import_module

_target = _import_module("metro_station.adapters.simulation.presets")
__all__ = getattr(_target, "__all__", ())


def __getattr__(name: str):
    return getattr(_target, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_target)))
