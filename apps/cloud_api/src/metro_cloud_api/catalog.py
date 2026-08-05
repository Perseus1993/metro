from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Catalog:
    version: str
    spec_version: str
    stations: frozenset[str]
    design_templates: frozenset[str]
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> Catalog:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=str(raw["catalog_version"]),
            spec_version=str(raw["spec_version"]),
            stations=frozenset(map(str, raw["stations"])),
            design_templates=frozenset(map(str, raw["design_templates"])),
            raw=raw,
        )
