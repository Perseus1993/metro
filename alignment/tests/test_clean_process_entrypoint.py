from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runner_starts_in_a_clean_python_process() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_alignment_scene.py"),
            "--list-scenes",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert '"platform_boarding"' in result.stdout
