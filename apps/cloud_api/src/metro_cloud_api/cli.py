from __future__ import annotations

import argparse

import uvicorn

from .config import Settings
from .worker import Worker


def api_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    uvicorn.run("metro_cloud_api.api:app", host=args.host, port=args.port)


def worker_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    worker = Worker(Settings.from_env())
    worker.recover_interrupted()
    if args.once:
        worker.run_once()
        return
    worker.run_forever()
