"""Build fact_od_pair_60min/ — OD 对小时事实表（全量版，按月分区）。

数据源: data/processed/od_nonzero_60min_2025H1.csv
全量 2025H1 OD 数据，181 天 × 17 时段 × 237×237 OD 矩阵。
"""

from __future__ import annotations

from collections import defaultdict
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

TABLE_NAME = "fact_od_pair_60min"
CHUNKSIZE = 500_000
PK_COLS = ["date", "hour", "origin_station_id", "destination_station_id"]
AGG_GROUP = PK_COLS + [
    "origin_station",
    "destination_station",
    "source_batch",
    "batch_id",
    "month",
]
OUT_COLS = [
    "date",
    "hour",
    "month",
    "origin_station_id",
    "destination_station_id",
    "origin_station",
    "destination_station",
    "od_count",
    "origin_line",
    "source_batch",
    "batch_id",
]


def _aggregate_od_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate rows to the OD fact primary key while preserving first origin_line."""
    return (
        df.groupby(AGG_GROUP, observed=True, sort=False)
        .agg(
            od_count=("od_count", "sum"),
            origin_line=("origin_line", "first"),
        )
        .reset_index()
    )


def build(
    registry_path: str | Path = "data/ods/station_id_registry.json",
    master_csv: str | Path = "output/xian_metro_station_master.csv",
    od_csv: str | Path = "data/processed/od_nonzero_60min_2025H1.csv",
    output_dir: str | Path = "data/ods/fact_od_pair_60min",
    tmp_dir: str | Path = "data/ods/.tmp_build",
) -> int:
    from scripts.ods.station_id_registry import StationIdRegistry

    output_dir = Path(output_dir)
    tmp_dir = Path(tmp_dir)
    tmp_out = tmp_dir / TABLE_NAME
    tmp_stage = tmp_dir / f"{TABLE_NAME}_mapped_chunks"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    if tmp_stage.exists():
        shutil.rmtree(tmp_stage)
    if tmp_out.exists():
        shutil.rmtree(tmp_out)
    tmp_stage.mkdir(parents=True, exist_ok=True)

    reg = StationIdRegistry(Path(registry_path), master_csv)

    # 1. Chunked read + station mapping. Each mapped chunk is written immediately
    #    so the full 79M-row CSV is never held in pandas at once.
    print(f"[AUDIT] {TABLE_NAME}: reading {od_csv} in chunks of {CHUNKSIZE} ...")
    unmatched: dict[str, int] = {}
    month_chunk_counts: dict[str, int] = defaultdict(int)
    total_raw = 0
    staged_rows = 0

    for chunk_idx, chunk in enumerate(
        pd.read_csv(od_csv, encoding="utf-8-sig", chunksize=CHUNKSIZE),
        start=1,
    ):
        # 规则 10
        chunk.columns = chunk.columns.str.strip()
        total_raw += len(chunk)

        # Map station names (lookup only!)
        def _lookup(name: str) -> int:
            sid = reg.lookup(name)
            if sid is not None:
                return sid
            unmatched[name] = unmatched.get(name, 0) + 1
            return -1

        chunk["origin_station_id"] = chunk["origin_station"].apply(_lookup).astype("int32")
        chunk["destination_station_id"] = (
            chunk["destination_station"].apply(_lookup).astype("int32")
        )

        chunk["date"] = pd.to_datetime(chunk["date"]).dt.date
        chunk["hour"] = chunk["hour"].astype("int32")
        chunk["month"] = chunk["date"].apply(lambda d: f"{d.year:04d}-{d.month:02d}")
        chunk["od_count"] = chunk["od_count"].astype("int64")
        chunk["source_batch"] = "od_reports_batch3"
        chunk["batch_id"] = "2025H1"

        chunk_out = _aggregate_od_rows(chunk[OUT_COLS])
        for month, part_df in chunk_out.groupby("month", sort=True):
            part_dir = tmp_stage / f"month={month}"
            part_dir.mkdir(parents=True, exist_ok=True)
            part_path = part_dir / f"chunk-{chunk_idx:05d}.parquet"
            part_df.drop(columns=["month"]).to_parquet(
                part_path,
                index=False,
                engine="pyarrow",
            )
            month_chunk_counts[str(month)] += 1
            staged_rows += len(part_df)

        if chunk_idx % 5 == 0:
            print(
                f"[AUDIT] chunks_read={chunk_idx} raw_rows={total_raw} "
                f"staged_rows={staged_rows}"
            )

    print(f"[AUDIT] total raw_rows={total_raw}")

    if unmatched:
        for name, cnt in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            print(f"[AUDIT][UNMATCHED] station_name={name} count={cnt}")
        raise SystemExit(
            f"[FATAL] {len(unmatched)} unmatched stations in OD data, ODS build aborted."
        )

    months = sorted(month_chunk_counts)
    if not months:
        raise SystemExit(f"[FATAL] {TABLE_NAME}: no rows staged from {od_csv}")

    # 2. Final aggregate one month at a time to catch duplicate PKs crossing CSV chunks.
    tmp_out.mkdir(parents=True, exist_ok=True)

    total_written = 0
    for month in months:
        stage_dir = tmp_stage / f"month={month}"
        month_df = pd.read_parquet(stage_dir, engine="pyarrow")
        if "month" in month_df.columns:
            month_df = month_df.drop(columns=["month"])
        month_df["month"] = month

        out = _aggregate_od_rows(month_df)
        duplicated_pk = out.duplicated(subset=PK_COLS)
        if duplicated_pk.any():
            examples = out.loc[duplicated_pk, PK_COLS].head(5).to_dict("records")
            raise AssertionError(f"PK not unique after aggregation: {examples}")

        assert (out["origin_station_id"] >= 0).all(), "Negative origin_station_id"
        assert (out["destination_station_id"] >= 0).all(), "Negative destination_station_id"

        part_df = out.drop(columns=["month"])
        part_dir = tmp_out / f"month={month}"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / "part.parquet"
        part_df.to_parquet(part_path, index=False, engine="pyarrow")
        n = len(part_df)
        total_written += n
        fsize_kb = part_path.stat().st_size / 1024
        print(
            f"[AUDIT] partition month={month}: rows={n} "
            f"chunks={month_chunk_counts[month]} size={fsize_kb:.1f}KB"
        )

    print(f"[AUDIT] {TABLE_NAME}: rows={total_written} PK_unique=True")

    # 3. Backup replace
    _backup_replace_dir(tmp_out, output_dir)
    shutil.rmtree(tmp_stage)
    print(f"[AUDIT] {TABLE_NAME} written: {output_dir}")

    return total_written


def _backup_replace_dir(tmp_dir: Path, formal_dir: Path) -> None:
    """Best-effort backup replace for directories."""
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


if __name__ == "__main__":
    build()
