from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any


def emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("usage: python -m metro_cloud_api.child <kind> <spec.json> <output_dir>",
              file=sys.stderr)
        return 2
    kind, spec_path, output_path = args
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        from .runners import get_runner_by_kind

        runner = get_runner_by_kind(kind)
        emit({"type": "meta", "runner_kind": runner.kind, "runner_version": runner.version})
        runner.run(
            spec,
            output_dir,
            lambda current, total: emit(
                {"type": "progress", "current": current, "total": total}
            ),
        )
    except Exception as exc:  # noqa: BLE001 - process boundary must serialize every failure
        emit(
            {"type": "error", "kind": "runner_exception",
             "message": f"{type(exc).__name__}: {exc}"}
        )
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
