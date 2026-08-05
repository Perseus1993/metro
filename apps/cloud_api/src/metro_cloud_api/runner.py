from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol


ProgressCallback = Callable[[int, int], None]


class SimulationRunner(Protocol):
    kind: str
    version: str

    def run(
        self,
        spec: dict[str, Any],
        output_dir: Path,
        on_progress: ProgressCallback,
    ) -> None: ...
