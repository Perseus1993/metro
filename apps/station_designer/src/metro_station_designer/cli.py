from __future__ import annotations

import argparse
from collections.abc import Sequence

from .server import serve_design_inspector


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the metro station designer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(arguments)
    serve_design_inspector(args.host, args.port)
