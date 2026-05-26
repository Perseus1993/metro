from __future__ import annotations

from .schema import DesignElement


def gate_direction(element: DesignElement) -> str:
    direction = element.gate_direction or element.metadata.get("gate_direction", "bidirectional")
    return str(direction) if direction in {"entry", "exit", "bidirectional"} else "bidirectional"


def vertical_direction(element: DesignElement) -> str:
    direction = element.direction or element.metadata.get("direction")
    if direction in {"up", "down", "both"}:
        return str(direction)

    lowered = f"{element.id} {element.label}".lower()
    if "down" in lowered or "下" in lowered:
        return "down"
    if "up" in lowered or "上" in lowered:
        return "up"
    return "both"


def platform_line_id(element: DesignElement) -> str:
    return str(element.line_id or element.metadata.get("line_id", "default"))


def platform_direction(element: DesignElement) -> str:
    direction = element.direction or element.metadata.get("direction", "down")
    return str(direction if direction in {"up", "down"} else "down")
