from __future__ import annotations

import argparse
from pathlib import Path

from metro_station_acceptance.blind_trajectory_export import (
    export_anonymized_xy_observations,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export anonymous id,t,x,y observations from simulation truth.",
    )
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = export_anonymized_xy_observations(args.replay, args.output)
    print(f"[BLIND TRAJECTORY EXPORT] observations={count} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
