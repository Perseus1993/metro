"""Build ODS — 统一入口脚本。

按依赖顺序执行:
1. station_id_registry → JSON
2. dim_station → Parquet
3. dim_calendar → Parquet
4. dim_weather_hourly → Parquet
5. fact_station_flow_hourly → Parquet
6. fact_section_flow_hourly → 分区 Parquet
7. fact_od_pair_60min → 分区 Parquet（全量版）
8. ADS panels → Parquet (from ODS)

用法:
    python scripts/ods/build_ods.py
    python scripts/ods/build_ods.py --only dim_station dim_calendar
    python scripts/ods/build_ods.py --skip fact_section_flow_hourly
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

_TZ_CST = timezone(timedelta(hours=8))

# ─────────────────────────────────────────────
# Step definitions
# ─────────────────────────────────────────────
STEPS = [
    "dim_station",
    "dim_calendar",
    "dim_weather_hourly",
    "fact_station_flow_hourly",
    "fact_section_flow_hourly",
    "fact_od_pair_60min",
    "ads",
]


def _write_manifest(
    table_name: str,
    output_path: Path,
    row_count: int,
    source_batch: str,
    batch_id: str = "2025H1",
    partitions: int = 1,
    pk_unique: bool = True,
) -> None:
    """Write a sidecar manifest.json next to the table output."""
    if output_path.is_dir():
        manifest_path = output_path / "_manifest.json"
    else:
        manifest_path = output_path.with_name(output_path.stem + "_manifest.json")

    payload = {
        "table_name": table_name,
        "ingest_time": datetime.now(_TZ_CST).isoformat(),
        "source_batch": source_batch,
        "batch_id": batch_id,
        "build_version": "v3",
        "row_count": row_count,
        "partitions": partitions,
        "pk_unique": pk_unique,
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[AUDIT] manifest written: {manifest_path}")


def run_dim_station() -> None:
    from scripts.ods.dim_station import build

    df = build()
    _write_manifest(
        "dim_station",
        Path("data/ods/dim_station.parquet"),
        len(df),
        "station_master",
    )


def run_dim_calendar() -> None:
    from scripts.ods.dim_calendar import build

    df = build()
    _write_manifest(
        "dim_calendar",
        Path("data/ods/dim_calendar.parquet"),
        len(df),
        "calendar_gov_2025",
    )


def run_dim_weather_hourly() -> None:
    from scripts.ods.dim_weather_hourly import build

    df = build()
    _write_manifest(
        "dim_weather_hourly",
        Path("data/ods/dim_weather_hourly.parquet"),
        len(df),
        "weather_openmeteo_v2",
    )


def run_fact_station_flow_hourly() -> None:
    from scripts.ods.fact_station_flow_hourly import build

    df = build()
    _write_manifest(
        "fact_station_flow_hourly",
        Path("data/ods/fact_station_flow_hourly.parquet"),
        len(df),
        "reports_batch3",
    )


def run_fact_section_flow_hourly() -> None:
    from scripts.ods.fact_section_flow_hourly import build

    total = build()
    out_dir = Path("data/ods/fact_section_flow_hourly")
    n_parts = len(list(out_dir.glob("month=*"))) if out_dir.exists() else 0
    _write_manifest(
        "fact_section_flow_hourly",
        out_dir,
        total,
        "reports_batch3",
        partitions=n_parts,
    )


def run_fact_od_pair_60min() -> None:
    from scripts.ods.fact_od_pair_60min import build

    total = build()
    out_dir = Path("data/ods/fact_od_pair_60min")
    n_parts = len(list(out_dir.glob("month=*"))) if out_dir.exists() else 0
    _write_manifest(
        "fact_od_pair_60min",
        out_dir,
        total,
        "od_reports_batch3",
        partitions=n_parts,
    )


def run_ads() -> None:
    from scripts.ods.build_ads import build_all

    build_all()


STEP_FUNCS = {
    "dim_station": run_dim_station,
    "dim_calendar": run_dim_calendar,
    "dim_weather_hourly": run_dim_weather_hourly,
    "fact_station_flow_hourly": run_fact_station_flow_hourly,
    "fact_section_flow_hourly": run_fact_section_flow_hourly,
    "fact_od_pair_60min": run_fact_od_pair_60min,
    "ads": run_ads,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ODS layer.")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Only build these tables.",
    )
    parser.add_argument(
        "--skip",
        nargs="*",
        default=None,
        help="Skip these tables.",
    )
    args = parser.parse_args()

    steps_to_run = list(STEPS)
    if args.only:
        steps_to_run = [s for s in STEPS if s in args.only]
    if args.skip:
        steps_to_run = [s for s in steps_to_run if s not in args.skip]

    print(f"[AUDIT] ODS build start: steps={steps_to_run}")
    overall_start = time.time()

    for step in steps_to_run:
        print(f"\n{'=' * 60}")
        print(f"[AUDIT] Building: {step}")
        print(f"{'=' * 60}")
        t0 = time.time()
        STEP_FUNCS[step]()
        elapsed = time.time() - t0
        print(f"[AUDIT] {step} done in {elapsed:.1f}s")

    overall_elapsed = time.time() - overall_start
    print(f"\n{'=' * 60}")
    print(f"[AUDIT] ODS build complete: {len(steps_to_run)} tables in {overall_elapsed:.1f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
