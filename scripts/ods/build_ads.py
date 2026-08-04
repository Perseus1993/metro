"""Build ADS panels from ODS — 分析面板层。

ADS tables (all built from ODS only):
  - data/ads/ads_station_hourly_panel.parquet
  - data/ads/ads_section_hourly_panel.parquet
  - data/ads/ads_network_hourly_panel.parquet
  - data/ads/ads_od_network_hourly_panel.parquet  (network-level OD total)

Usage:
  python scripts/ods/build_ads.py
  python scripts/ods/build_ads.py --skip od_network
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from metro_data_warehouse.ods.reader import ODS, ODSPaths  # noqa: E402

_TZ_CST = timezone(timedelta(hours=8))


def _write_manifest(
    table_name: str,
    output_path: Path,
    row_count: int,
    source_batch: str,
    batch_id: str = "2025H1",
    partitions: int = 1,
    pk_unique: bool = True,
) -> None:
    if output_path.is_dir():
        manifest_path = output_path / "_manifest.json"
    else:
        manifest_path = output_path.with_name(output_path.stem + "_manifest.json")

    payload = {
        "table_name": table_name,
        "ingest_time": datetime.now(_TZ_CST).isoformat(),
        "source_batch": source_batch,
        "batch_id": batch_id,
        "build_version": "v1",
        "row_count": row_count,
        "partitions": partitions,
        "pk_unique": pk_unique,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[AUDIT] manifest written: {manifest_path}")


def _backup_replace_file(tmp_file: Path, formal_file: Path) -> None:
    bak = formal_file.with_name(formal_file.name + ".bak")
    formal_file.parent.mkdir(parents=True, exist_ok=True)

    if formal_file.exists():
        if bak.exists():
            bak.unlink()
        formal_file.rename(bak)

    try:
        tmp_file.rename(formal_file)
    except OSError as exc:
        if bak.exists() and not formal_file.exists():
            bak.rename(formal_file)
        raise SystemExit(f"[AUDIT][FAILED] rename failed: {exc}") from exc

    if bak.exists():
        bak.unlink()


def _backup_replace_dir(tmp_dir: Path, formal_dir: Path) -> None:
    bak_dir = formal_dir.with_name(formal_dir.name + ".bak")

    if formal_dir.exists():
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
        formal_dir.rename(bak_dir)

    try:
        tmp_dir.rename(formal_dir)
    except OSError as exc:
        if bak_dir.exists() and not formal_dir.exists():
            bak_dir.rename(formal_dir)
        raise SystemExit(f"[AUDIT][FAILED] rename failed: {exc}") from exc

    if bak_dir.exists():
        shutil.rmtree(bak_dir)


def _ensure_dirs(paths: ODSPaths) -> tuple[Path, Path]:
    ads_dir = paths.ads_dir
    tmp_dir = ads_dir / ".tmp_build"
    ads_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return ads_dir, tmp_dir


def _build_weather_calendar() -> pd.DataFrame:
    weather = ODS.dim_weather_hourly()
    cal = ODS.dim_calendar()

    # Avoid source_batch collisions in joins; keep provenance in manifests instead.
    for col in ["source_batch"]:
        if col in weather.columns:
            weather = weather.drop(columns=[col])
        if col in cal.columns:
            cal = cal.drop(columns=[col])

    base = weather.merge(cal, on="date", how="left", validate="many_to_one")
    if base["day_of_week"].isna().any():
        raise SystemExit("[AUDIT][FATAL] weather_calendar join produced NaN day_of_week")
    if base.duplicated(subset=["date", "hour"]).any():
        raise SystemExit("[AUDIT][FATAL] weather_calendar (date,hour) not unique")
    print(f"[AUDIT] weather_calendar rows={len(base)}")
    return base


def build_station_panel(paths: ODSPaths, tmp_dir: Path, weather_calendar: pd.DataFrame) -> int:
    fact = ODS.fact_station_flow_hourly()
    dim_station = ODS.dim_station()

    # Avoid duplicate station_name columns
    if "station_name" in fact.columns:
        fact = fact.drop(columns=["station_name"])

    out = fact.merge(weather_calendar, on=["date", "hour"], how="left", validate="many_to_one")
    out = out.merge(dim_station, on=["station_id"], how="left", validate="many_to_one")

    if out["temperature_2m"].isna().any():
        raise SystemExit("[AUDIT][FATAL] station_panel join missing weather rows")
    if out["station_name"].isna().any():
        raise SystemExit("[AUDIT][FATAL] station_panel join missing dim_station rows")

    # Audit PK uniqueness
    if out.duplicated(subset=["date", "hour", "station_id"]).any():
        raise SystemExit("[AUDIT][FATAL] station_panel PK not unique")

    # Reorder a bit (keep compatible columns near front)
    preferred = [
        "date",
        "hour",
        "station_id",
        "station_name",
        "entry_count",
        "exit_count",
        "total_count",
    ]
    cols = preferred + [c for c in out.columns if c not in preferred]
    out = out[cols]

    tmp_file = tmp_dir / "ads_station_hourly_panel.parquet"
    out.to_parquet(tmp_file, index=False, engine="pyarrow")
    _backup_replace_file(tmp_file, paths.ads_station_hourly_panel)
    _write_manifest(
        "ads_station_hourly_panel",
        paths.ads_station_hourly_panel,
        len(out),
        source_batch="ods_join",
        partitions=1,
        pk_unique=True,
    )
    print(f"[AUDIT] ads_station_hourly_panel written: rows={len(out)}")
    return len(out)


def build_section_panel(paths: ODSPaths, tmp_dir: Path, weather_calendar: pd.DataFrame) -> int:
    fact = ODS.fact_section_flow_hourly()

    # Build a compatible "section" column like processed panel: from-to
    if "section" not in fact.columns:
        fact = fact.copy()
        fact["section"] = fact["from_station"].astype(str) + "-" + fact["to_station"].astype(str)

    out = fact.merge(weather_calendar, on=["date", "hour"], how="left", validate="many_to_one")
    if out["temperature_2m"].isna().any():
        raise SystemExit("[AUDIT][FATAL] section_panel join missing weather rows")

    # Audit PK uniqueness
    pk_cols = ["date", "hour", "section_id"]
    if out.duplicated(subset=pk_cols).any():
        raise SystemExit("[AUDIT][FATAL] section_panel PK not unique (date,hour,section_id)")

    tmp_file = tmp_dir / "ads_section_hourly_panel.parquet"
    out.to_parquet(tmp_file, index=False, engine="pyarrow")
    _backup_replace_file(tmp_file, paths.ads_section_hourly_panel)
    _write_manifest(
        "ads_section_hourly_panel",
        paths.ads_section_hourly_panel,
        len(out),
        source_batch="ods_join",
        partitions=1,
        pk_unique=True,
    )
    print(f"[AUDIT] ads_section_hourly_panel written: rows={len(out)}")
    return len(out)


def build_network_panel(paths: ODSPaths, tmp_dir: Path, weather_calendar: pd.DataFrame) -> int:
    fact = ODS.fact_station_flow_hourly()
    net = (
        fact.groupby(["date", "hour"], observed=True)
        .agg(
            entry_count=("entry_count", "sum"),
            exit_count=("exit_count", "sum"),
            enter_exit_count=("total_count", "sum"),
        )
        .reset_index()
    )
    out = net.merge(weather_calendar, on=["date", "hour"], how="left", validate="many_to_one")
    if out["temperature_2m"].isna().any():
        raise SystemExit("[AUDIT][FATAL] network_panel join missing weather rows")
    if out.duplicated(subset=["date", "hour"]).any():
        raise SystemExit("[AUDIT][FATAL] network_panel PK not unique")

    tmp_file = tmp_dir / "ads_network_hourly_panel.parquet"
    out.to_parquet(tmp_file, index=False, engine="pyarrow")
    _backup_replace_file(tmp_file, paths.ads_network_hourly_panel)
    _write_manifest(
        "ads_network_hourly_panel",
        paths.ads_network_hourly_panel,
        len(out),
        source_batch="ods_agg_station",
        partitions=1,
        pk_unique=True,
    )
    print(f"[AUDIT] ads_network_hourly_panel written: rows={len(out)}")
    return len(out)


def build_od_network_panel(paths: ODSPaths, tmp_dir: Path, weather_calendar: pd.DataFrame) -> int:
    """Network-level OD total per hour: sum(od_count) by (date,hour)."""
    # Stream aggregate from parquet dataset to avoid loading 79M rows into pandas.
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
    except Exception as exc:
        raise SystemExit(f"[AUDIT][FATAL] pyarrow required: {exc}") from exc

    od_dir = paths.fact_od_pair_60min
    dataset = ds.dataset(str(od_dir), format="parquet", partitioning="hive")
    scanner = dataset.scanner(columns=["date", "hour", "od_count"], batch_size=1_000_000)

    acc: dict[tuple[object, int], int] = defaultdict(int)
    t0 = time.time()
    n_rows = 0
    n_batches = 0
    for batch in scanner.to_batches():
        n_batches += 1
        n_rows += batch.num_rows
        table = pa.Table.from_batches([batch])
        grouped = table.group_by(["date", "hour"]).aggregate([("od_count", "sum")])
        dates = grouped["date"].to_pylist()
        hours = grouped["hour"].to_pylist()
        sums = grouped["od_count_sum"].to_pylist()
        for d, h, s in zip(dates, hours, sums):
            acc[(d, int(h))] += int(s)
        if n_batches % 50 == 0:
            elapsed = time.time() - t0
            print(
                f"[AUDIT] od_network scan batches={n_batches} rows={n_rows} elapsed={elapsed:.1f}s"
            )

    rows = [{"date": d, "hour": h, "od_total": v} for (d, h), v in acc.items()]
    od_totals = pd.DataFrame(rows, columns=["date", "hour", "od_total"])
    if not od_totals.empty:
        od_totals["date"] = pd.to_datetime(od_totals["date"]).dt.date
        od_totals["hour"] = od_totals["hour"].astype("int32")
        od_totals["od_total"] = od_totals["od_total"].astype("int64")

    weather_base = weather_calendar.copy()
    weather_base["date"] = pd.to_datetime(weather_base["date"]).dt.date
    weather_base["hour"] = weather_base["hour"].astype("int32")

    service_hours = ODS.fact_station_flow_hourly()[["date", "hour"]].drop_duplicates()
    service_hours["date"] = pd.to_datetime(service_hours["date"]).dt.date
    service_hours["hour"] = service_hours["hour"].astype("int32")
    out = service_hours.merge(
        weather_base,
        on=["date", "hour"],
        how="left",
        validate="one_to_one",
    )
    out = out.merge(od_totals, on=["date", "hour"], how="left", validate="one_to_one")
    zero_filled_hours = int(out["od_total"].isna().sum())
    out["od_total"] = out["od_total"].fillna(0).astype("int64")
    preferred = ["date", "hour", "od_total"]
    out = out[preferred + [c for c in out.columns if c not in preferred]]
    if out["temperature_2m"].isna().any():
        raise SystemExit("[AUDIT][FATAL] od_network_panel join missing weather rows")
    if out.duplicated(subset=["date", "hour"]).any():
        raise SystemExit("[AUDIT][FATAL] od_network_panel PK not unique")

    tmp_file = tmp_dir / "ads_od_network_hourly_panel.parquet"
    out.to_parquet(tmp_file, index=False, engine="pyarrow")
    _backup_replace_file(tmp_file, paths.ads_od_network_hourly_panel)
    _write_manifest(
        "ads_od_network_hourly_panel",
        paths.ads_od_network_hourly_panel,
        len(out),
        source_batch="ods_agg_od",
        partitions=1,
        pk_unique=True,
    )
    print(
        f"[AUDIT] ads_od_network_hourly_panel written: rows={len(out)} "
        f"zero_filled_hours={zero_filled_hours}"
    )
    return len(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ADS panels from ODS.")
    parser.add_argument(
        "--skip",
        nargs="*",
        default=None,
        help="Skip steps: station section network od_network",
    )
    args = parser.parse_args()
    skip = set(args.skip or [])
    build_all(skip)


def build_all(skip: set[str] | None = None) -> None:
    """Build all ADS panels from ODS."""
    skip = set(skip or [])
    paths = ODS._PATHS
    _, tmp_dir = _ensure_dirs(paths)

    print("[AUDIT] ADS build start")
    weather_calendar = _build_weather_calendar()

    if "station" not in skip:
        build_station_panel(paths, tmp_dir, weather_calendar)
    if "section" not in skip:
        build_section_panel(paths, tmp_dir, weather_calendar)
    if "network" not in skip:
        build_network_panel(paths, tmp_dir, weather_calendar)
    if "od_network" not in skip:
        build_od_network_panel(paths, tmp_dir, weather_calendar)

    print("[AUDIT] ADS build complete")


if __name__ == "__main__":
    main()
