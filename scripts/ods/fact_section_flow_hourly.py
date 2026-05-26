"""Build fact_section_flow_hourly/ — 区间小时流量事实表（按月分区）。

数据源: data/processed/section_flow_15min_2025H1.csv (3GB+)
处理: 分块读取 → registry.lookup() → 聚合到 hourly → 按月写 tmp → 审计 → backup 替换
"""

from __future__ import annotations

import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.station_catalog import line_label_to_ref  # noqa: E402

CHUNKSIZE = 500_000
TABLE_NAME = "fact_section_flow_hourly"


def build(
    registry_path: str | Path = "data/ods/station_id_registry.json",
    master_csv: str | Path = "output/xian_metro_station_master.csv",
    flow_csv: str | Path = "data/processed/section_flow_15min_2025H1.csv",
    output_dir: str | Path = "data/ods/fact_section_flow_hourly",
    tmp_dir: str | Path = "data/ods/.tmp_build",
) -> int:
    from scripts.ods.station_id_registry import StationIdRegistry

    output_dir = Path(output_dir)
    tmp_dir = Path(tmp_dir)
    tmp_out = tmp_dir / TABLE_NAME

    reg = StationIdRegistry(Path(registry_path), master_csv)

    # 1. Chunked read + aggregate
    print(f"[AUDIT] {TABLE_NAME}: reading {flow_csv} in chunks of {CHUNKSIZE} ...")
    agg: dict[tuple, dict] = defaultdict(lambda: {"flow": 0, "file_count": set()})
    unmatched: dict[str, int] = {}
    total_raw_rows = 0

    for chunk_idx, chunk in enumerate(
        pd.read_csv(flow_csv, encoding="utf-8-sig", chunksize=CHUNKSIZE)
    ):
        # 规则 10
        chunk.columns = chunk.columns.str.strip()
        total_raw_rows += len(chunk)

        for _, row in chunk.iterrows():
            from_name = str(row["from_station"]).strip()
            to_name = str(row["to_station"]).strip()
            from_id = reg.lookup(from_name)
            to_id = reg.lookup(to_name)

            if from_id is None:
                unmatched[from_name] = unmatched.get(from_name, 0) + 1
                continue
            if to_id is None:
                unmatched[to_name] = unmatched.get(to_name, 0) + 1
                continue

            date_str = str(row["date"]).strip()
            hour = int(row["hour"])
            line_label = str(row["line_label"]).strip()
            line_ref = line_label_to_ref(line_label)
            direction = str(row["direction"]).strip()

            key = (
                date_str,
                hour,
                line_ref,
                line_label,
                direction,
                from_id,
                to_id,
                from_name,
                to_name,
            )
            agg[key]["flow"] += int(row["section_flow"])

        if (chunk_idx + 1) % 10 == 0:
            print(
                f"[AUDIT] chunks_read={chunk_idx + 1} raw_rows={total_raw_rows} agg_keys={len(agg)}"
            )

    print(f"[AUDIT] total raw_rows={total_raw_rows} agg_keys={len(agg)}")

    # 2. Report unmatched
    if unmatched:
        for name, cnt in sorted(unmatched.items(), key=lambda kv: -kv[1]):
            print(f"[AUDIT][UNMATCHED] station_name={name} count={cnt}")
        raise SystemExit(
            f"[FATAL] {len(unmatched)} unmatched stations in section flow, ODS build aborted."
        )

    # 3. Build DataFrame
    records = []
    for key, val in agg.items():
        date_str, hour, line_ref, line_label, direction, from_id, to_id, from_name, to_name = key
        section_id = f"{line_ref}_{direction}_{from_id:03d}_{to_id:03d}"
        month = date_str[:7]  # YYYY-MM
        records.append(
            {
                "date": date_str,
                "hour": hour,
                "month": month,
                "line_ref": line_ref,
                "line_label": line_label,
                "direction": direction,
                "section_id": section_id,
                "from_station_id": from_id,
                "to_station_id": to_id,
                "from_station": from_name,
                "to_station": to_name,
                "section_flow_hourly": val["flow"],
                "source_batch": "reports_batch3",
                "batch_id": "2025H1",
            }
        )

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["hour"] = df["hour"].astype("int32")
    df["from_station_id"] = df["from_station_id"].astype("int32")
    df["to_station_id"] = df["to_station_id"].astype("int32")
    df["section_flow_hourly"] = df["section_flow_hourly"].astype("int64")

    # 4. Audit: PK uniqueness
    pk_cols = ["date", "hour", "line_ref", "direction", "from_station_id", "to_station_id"]
    pk = df[pk_cols].apply(tuple, axis=1)
    assert pk.is_unique, f"PK not unique! duplicates={pk.duplicated().sum()}"
    assert df["from_station_id"].notna().all(), "NaN from_station_id"
    assert df["to_station_id"].notna().all(), "NaN to_station_id"

    # 5. Write to tmp by month partition
    if tmp_out.exists():
        shutil.rmtree(tmp_out)
    tmp_out.mkdir(parents=True, exist_ok=True)

    months = sorted(df["month"].unique())
    total_written = 0
    for m in months:
        part_df = df.loc[df["month"] == m].drop(columns=["month"])
        part_dir = tmp_out / f"month={m}"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / "part.parquet"
        part_df.to_parquet(part_path, index=False, engine="pyarrow")
        n = len(part_df)
        assert n > 0, f"Empty partition month={m}!"
        total_written += n
        fsize_kb = part_path.stat().st_size / 1024
        print(f"[AUDIT] partition month={m}: rows={n} size={fsize_kb:.1f}KB")

    print(
        f"[AUDIT] {TABLE_NAME}: total_rows={total_written} partitions={len(months)} PK_unique=True"
    )

    # 6. Backup replace
    _backup_replace_dir(tmp_out, output_dir)
    print(f"[AUDIT] {TABLE_NAME} written: {output_dir}")

    return total_written


def _backup_replace_dir(tmp_dir: Path, formal_dir: Path) -> None:
    """Best-effort backup replace for directories."""
    bak_dir = formal_dir.with_name(formal_dir.name + ".bak")

    # old → bak
    if formal_dir.exists():
        if bak_dir.exists():
            shutil.rmtree(bak_dir)
        formal_dir.rename(bak_dir)

    # tmp → formal
    try:
        tmp_dir.rename(formal_dir)
    except OSError as exc:
        if bak_dir.exists() and not formal_dir.exists():
            bak_dir.rename(formal_dir)
        raise SystemExit(f"[AUDIT][FAILED] rename failed: {exc}") from exc

    # delete bak
    if bak_dir.exists():
        shutil.rmtree(bak_dir)


if __name__ == "__main__":
    build()
