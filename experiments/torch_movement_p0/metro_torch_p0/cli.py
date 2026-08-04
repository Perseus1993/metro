"""Command-line entry point for regenerating P0 evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from .evidence import generate_evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated Metro Torch P0 evidence suite.")
    parser.add_argument("--out", type=Path, default=Path("evidence"), help="Output directory relative to this project.")
    args = parser.parse_args()
    json_path, markdown_path, verdict = generate_evidence(args.out)
    print(f"{verdict}\nJSON: {json_path}\nReport: {markdown_path}")
