from __future__ import annotations

import ast
from pathlib import Path


def test_simulation_package_import_is_isolated() -> None:
    source = Path(__file__).parents[1] / "src" / "metro_cloud_api"
    allowed = source / "runners" / "metro_station.py"
    violations = []
    for path in source.rglob("*.py"):
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            if any(name == "metro_station" or name.startswith("metro_station.") for name in names):
                violations.append(str(path.relative_to(source)))
    assert violations == []
