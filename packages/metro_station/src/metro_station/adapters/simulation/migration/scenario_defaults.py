from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def migrate_legacy_scenario_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade an old model to the sole active Goal Graph runtime."""

    migrated = dict(options)
    migrated["goal_graph_mode"] = "active"
    return migrated
