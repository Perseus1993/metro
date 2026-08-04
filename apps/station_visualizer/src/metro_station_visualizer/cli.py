from __future__ import annotations

import argparse
from collections.abc import Sequence
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import ROOT


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the metro station visualizer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(arguments)
    handler = lambda *values, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *values,
        directory=str(ROOT),
        **kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"[VISUALIZER] serving=http://{args.host}:{args.port}/animation_demo.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[VISUALIZER] server stopped")
