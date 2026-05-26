"""Audit AFC channel time and station coverage.

The script scans only non-sensitive coverage fields from the large AFC CSVs:
dates, line ids, station ids, record/transaction types, and money columns.
It deliberately does not read or output card numbers, user ids, order ids,
or ticket physical ids.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pyarrow.csv as pv
import pyarrow.compute as pc
import pandas as pd


CHANNELS = ("长安通", "地铁票", "交通部一卡通", "二维码")
CARD_CHANNELS = {"长安通", "地铁票", "交通部一卡通"}

CARD_USECOLS = [
    "BALANCE_DATE",
    "TRADE_DATE",
    "TRADE_TIME",
    "LINE_ID",
    "ENTRY_STATION_ID",
    "EXIT_STATION_ID",
    "TRADE_TYPE",
    "TRADE_STATE",
    "TICKET_TYPE",
    "TRADE_MONEY",
]
QR_USECOLS = [
    "BALANCE_DATE",
    "TRADE_DATE",
    "TRADE_TIME",
    "LINE_ID",
    "STATION_ID",
    "RCD_TYPE",
    "TRADE_FLAG",
    "TRADE_MONEY",
]

DATE_RE = re.compile(r"^\d{8}$")
TIME_RE = re.compile(r"^\d{14}$")
PERIOD_RE = re.compile(r"(\d{8})_(\d{8})")


def _channel_from_name(path: Path) -> str | None:
    for channel in CHANNELS:
        if path.name.startswith(channel):
            return channel
    return None


def _period_from_name(path: Path) -> tuple[str | None, str | None]:
    match = PERIOD_RE.search(path.name)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _normalize(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.strip('"')


def _valid_values(s: pd.Series, *, zero_invalid: bool = False) -> pd.Series:
    out = _normalize(s)
    invalid = out.isna() | out.eq("") | out.str.lower().isin({"nan", "none", "null"})
    if zero_invalid:
        invalid = invalid | out.eq("0")
    return out[~invalid]


def _valid_dates(s: pd.Series) -> pd.Series:
    out = _valid_values(s)
    return out[out.str.match(DATE_RE, na=False)]


def _valid_times(s: pd.Series) -> pd.Series:
    out = _valid_values(s)
    return out[out.str.match(TIME_RE, na=False)]


def _update_minmax(current_min: str | None, current_max: str | None, values: pd.Series) -> tuple[str | None, str | None]:
    if values.empty:
        return current_min, current_max
    vmin = str(values.min())
    vmax = str(values.max())
    if current_min is None or vmin < current_min:
        current_min = vmin
    if current_max is None or vmax > current_max:
        current_max = vmax
    return current_min, current_max


def _counter_update(counter: Counter[str], values: pd.Series) -> None:
    if values.empty:
        return
    counter.update(values.value_counts(dropna=False).to_dict())


def _batch_col(batch, name: str):
    return batch.column(batch.schema.get_field_index(name))


def _mask_valid(arr, *, zero_invalid: bool = False, regex: str | None = None):
    mask = pc.is_valid(arr)
    if zero_invalid:
        mask = pc.and_(mask, pc.fill_null(pc.not_equal(arr, "0"), False))
    if regex is not None:
        mask = pc.and_(mask, pc.fill_null(pc.match_substring_regex(arr, regex), False))
    return mask


def _filtered(arr, *, zero_invalid: bool = False, regex: str | None = None):
    return pc.filter(arr, _mask_valid(arr, zero_invalid=zero_invalid, regex=regex))


def _counter_update_arrow(
    counter: Counter[str],
    arr,
    *,
    zero_invalid: bool = False,
    regex: str | None = None,
) -> None:
    vals = _filtered(arr, zero_invalid=zero_invalid, regex=regex)
    if len(vals) == 0:
        return
    for item in pc.value_counts(vals).to_pylist():
        value = item["values"]
        if value is not None:
            counter[str(value)] += int(item["counts"])


def _update_minmax_arrow(
    current_min: str | None,
    current_max: str | None,
    arr,
    *,
    regex: str | None = None,
) -> tuple[str | None, str | None]:
    vals = _filtered(arr, regex=regex)
    if len(vals) == 0:
        return current_min, current_max
    mm = pc.min_max(vals).as_py()
    vmin = mm.get("min")
    vmax = mm.get("max")
    if vmin is not None and (current_min is None or str(vmin) < current_min):
        current_min = str(vmin)
    if vmax is not None and (current_max is None or str(vmax) > current_max):
        current_max = str(vmax)
    return current_min, current_max


def _update_date_station_arrow(target: "Coverage", file_cov: "Coverage", dates, stations) -> None:
    mask = pc.and_(
        _mask_valid(dates, regex=r"^\d{8}$"),
        _mask_valid(stations, zero_invalid=True),
    )
    filtered_dates = pc.filter(dates, mask)
    filtered_stations = pc.filter(stations, mask)
    if len(filtered_dates) == 0:
        return
    pairs = pc.unique(pc.binary_join_element_wise(filtered_dates, filtered_stations, "|")).to_pylist()
    for pair in pairs:
        if not pair:
            continue
        date, station = str(pair).split("|", 1)
        target.balance_date_stations[date].add(station)
        file_cov.balance_date_stations[date].add(station)


def _station_line(code: str) -> str:
    try:
        n = int(code)
    except ValueError:
        return ""
    if n <= 0:
        return ""
    return str(n // 100)


def _iso_date(raw: str | None) -> str:
    if not raw or not DATE_RE.match(raw):
        return ""
    try:
        return datetime.strptime(raw, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def _iso_time(raw: str | None) -> str:
    if not raw or not TIME_RE.match(raw):
        return ""
    try:
        return datetime.strptime(raw, "%Y%m%d%H%M%S").isoformat(sep=" ")
    except ValueError:
        return ""


@dataclass
class Coverage:
    channel: str
    files: list[str] = field(default_factory=list)
    file_periods: list[str] = field(default_factory=list)
    size_bytes: int = 0
    rows: int = 0
    balance_counts: Counter[str] = field(default_factory=Counter)
    trade_date_counts: Counter[str] = field(default_factory=Counter)
    line_counts: Counter[str] = field(default_factory=Counter)
    trade_type_counts: Counter[str] = field(default_factory=Counter)
    trade_state_counts: Counter[str] = field(default_factory=Counter)
    ticket_type_counts: Counter[str] = field(default_factory=Counter)
    rcd_type_counts: Counter[str] = field(default_factory=Counter)
    trade_flag_counts: Counter[str] = field(default_factory=Counter)
    money_counts: Counter[str] = field(default_factory=Counter)
    station_counts: Counter[str] = field(default_factory=Counter)
    entry_station_counts: Counter[str] = field(default_factory=Counter)
    exit_station_counts: Counter[str] = field(default_factory=Counter)
    qr_station_counts: Counter[str] = field(default_factory=Counter)
    balance_date_stations: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    skipped_rows: int = 0
    balance_min: str | None = None
    balance_max: str | None = None
    trade_date_min: str | None = None
    trade_date_max: str | None = None
    trade_time_min: str | None = None
    trade_time_max: str | None = None


def _process_card_chunk(chunk: pd.DataFrame, target: Coverage, file_cov: Coverage) -> None:
    balance = _valid_dates(chunk["BALANCE_DATE"])
    trade_date = _valid_dates(chunk["TRADE_DATE"])
    trade_time = _valid_times(chunk["TRADE_TIME"])
    target.balance_min, target.balance_max = _update_minmax(target.balance_min, target.balance_max, balance)
    target.trade_date_min, target.trade_date_max = _update_minmax(target.trade_date_min, target.trade_date_max, trade_date)
    target.trade_time_min, target.trade_time_max = _update_minmax(target.trade_time_min, target.trade_time_max, trade_time)
    file_cov.balance_min, file_cov.balance_max = _update_minmax(file_cov.balance_min, file_cov.balance_max, balance)
    file_cov.trade_date_min, file_cov.trade_date_max = _update_minmax(file_cov.trade_date_min, file_cov.trade_date_max, trade_date)
    file_cov.trade_time_min, file_cov.trade_time_max = _update_minmax(file_cov.trade_time_min, file_cov.trade_time_max, trade_time)

    for cov in (target, file_cov):
        _counter_update(cov.balance_counts, balance)
        _counter_update(cov.trade_date_counts, trade_date)
        _counter_update(cov.line_counts, _valid_values(chunk["LINE_ID"]))
        _counter_update(cov.trade_type_counts, _valid_values(chunk["TRADE_TYPE"]))
        _counter_update(cov.trade_state_counts, _valid_values(chunk["TRADE_STATE"]))
        _counter_update(cov.ticket_type_counts, _valid_values(chunk["TICKET_TYPE"]))
        _counter_update(cov.money_counts, _valid_values(chunk["TRADE_MONEY"]))

    for col, counter_name in [
        ("ENTRY_STATION_ID", "entry_station_counts"),
        ("EXIT_STATION_ID", "exit_station_counts"),
    ]:
        stations = _valid_values(chunk[col], zero_invalid=True)
        getattr(target, counter_name).update(stations.value_counts(dropna=False).to_dict())
        getattr(file_cov, counter_name).update(stations.value_counts(dropna=False).to_dict())
        target.station_counts.update(stations.value_counts(dropna=False).to_dict())
        file_cov.station_counts.update(stations.value_counts(dropna=False).to_dict())

        if not stations.empty:
            by_date = pd.DataFrame({"date": _normalize(chunk.loc[stations.index, "BALANCE_DATE"]), "station": stations})
            by_date = by_date[by_date["date"].str.match(DATE_RE, na=False)]
            for date, group in by_date.groupby("date", observed=True):
                vals = set(group["station"].dropna().astype(str))
                target.balance_date_stations[str(date)].update(vals)
                file_cov.balance_date_stations[str(date)].update(vals)


def _process_qr_chunk(chunk: pd.DataFrame, target: Coverage, file_cov: Coverage) -> None:
    balance = _valid_dates(chunk["BALANCE_DATE"])
    trade_date = _valid_dates(chunk["TRADE_DATE"])
    trade_time = _valid_times(chunk["TRADE_TIME"])
    target.balance_min, target.balance_max = _update_minmax(target.balance_min, target.balance_max, balance)
    target.trade_date_min, target.trade_date_max = _update_minmax(target.trade_date_min, target.trade_date_max, trade_date)
    target.trade_time_min, target.trade_time_max = _update_minmax(target.trade_time_min, target.trade_time_max, trade_time)
    file_cov.balance_min, file_cov.balance_max = _update_minmax(file_cov.balance_min, file_cov.balance_max, balance)
    file_cov.trade_date_min, file_cov.trade_date_max = _update_minmax(file_cov.trade_date_min, file_cov.trade_date_max, trade_date)
    file_cov.trade_time_min, file_cov.trade_time_max = _update_minmax(file_cov.trade_time_min, file_cov.trade_time_max, trade_time)

    for cov in (target, file_cov):
        _counter_update(cov.balance_counts, balance)
        _counter_update(cov.trade_date_counts, trade_date)
        _counter_update(cov.line_counts, _valid_values(chunk["LINE_ID"]))
        _counter_update(cov.rcd_type_counts, _valid_values(chunk["RCD_TYPE"]))
        _counter_update(cov.trade_flag_counts, _valid_values(chunk["TRADE_FLAG"]))
        _counter_update(cov.money_counts, _valid_values(chunk["TRADE_MONEY"]))

    stations = _valid_values(chunk["STATION_ID"], zero_invalid=True)
    target.qr_station_counts.update(stations.value_counts(dropna=False).to_dict())
    file_cov.qr_station_counts.update(stations.value_counts(dropna=False).to_dict())
    target.station_counts.update(stations.value_counts(dropna=False).to_dict())
    file_cov.station_counts.update(stations.value_counts(dropna=False).to_dict())

    if not stations.empty:
        by_date = pd.DataFrame({"date": _normalize(chunk.loc[stations.index, "BALANCE_DATE"]), "station": stations})
        by_date = by_date[by_date["date"].str.match(DATE_RE, na=False)]
        for date, group in by_date.groupby("date", observed=True):
            vals = set(group["station"].dropna().astype(str))
            target.balance_date_stations[str(date)].update(vals)
            file_cov.balance_date_stations[str(date)].update(vals)


def _process_card_batch(batch, target: Coverage, file_cov: Coverage) -> None:
    balance = _batch_col(batch, "BALANCE_DATE")
    trade_date = _batch_col(batch, "TRADE_DATE")
    trade_time = _batch_col(batch, "TRADE_TIME")

    target.balance_min, target.balance_max = _update_minmax_arrow(
        target.balance_min, target.balance_max, balance, regex=r"^\d{8}$"
    )
    target.trade_date_min, target.trade_date_max = _update_minmax_arrow(
        target.trade_date_min, target.trade_date_max, trade_date, regex=r"^\d{8}$"
    )
    target.trade_time_min, target.trade_time_max = _update_minmax_arrow(
        target.trade_time_min, target.trade_time_max, trade_time, regex=r"^\d{14}$"
    )
    file_cov.balance_min, file_cov.balance_max = _update_minmax_arrow(
        file_cov.balance_min, file_cov.balance_max, balance, regex=r"^\d{8}$"
    )
    file_cov.trade_date_min, file_cov.trade_date_max = _update_minmax_arrow(
        file_cov.trade_date_min, file_cov.trade_date_max, trade_date, regex=r"^\d{8}$"
    )
    file_cov.trade_time_min, file_cov.trade_time_max = _update_minmax_arrow(
        file_cov.trade_time_min, file_cov.trade_time_max, trade_time, regex=r"^\d{14}$"
    )

    for cov in (target, file_cov):
        _counter_update_arrow(cov.balance_counts, balance, regex=r"^\d{8}$")
        _counter_update_arrow(cov.trade_date_counts, trade_date, regex=r"^\d{8}$")
        _counter_update_arrow(cov.line_counts, _batch_col(batch, "LINE_ID"))
        _counter_update_arrow(cov.trade_type_counts, _batch_col(batch, "TRADE_TYPE"))
        _counter_update_arrow(cov.trade_state_counts, _batch_col(batch, "TRADE_STATE"))
        _counter_update_arrow(cov.ticket_type_counts, _batch_col(batch, "TICKET_TYPE"))
        _counter_update_arrow(cov.money_counts, _batch_col(batch, "TRADE_MONEY"))

    for col, counter_name in [
        ("ENTRY_STATION_ID", "entry_station_counts"),
        ("EXIT_STATION_ID", "exit_station_counts"),
    ]:
        station_arr = _batch_col(batch, col)
        vals = _filtered(station_arr, zero_invalid=True)
        if len(vals) > 0:
            for item in pc.value_counts(vals).to_pylist():
                station = item["values"]
                if station is None:
                    continue
                station = str(station)
                count = int(item["counts"])
                getattr(target, counter_name)[station] += count
                getattr(file_cov, counter_name)[station] += count
                target.station_counts[station] += count
                file_cov.station_counts[station] += count
        _update_date_station_arrow(target, file_cov, balance, station_arr)


def _process_qr_batch(batch, target: Coverage, file_cov: Coverage) -> None:
    balance = _batch_col(batch, "BALANCE_DATE")
    trade_date = _batch_col(batch, "TRADE_DATE")
    trade_time = _batch_col(batch, "TRADE_TIME")

    target.balance_min, target.balance_max = _update_minmax_arrow(
        target.balance_min, target.balance_max, balance, regex=r"^\d{8}$"
    )
    target.trade_date_min, target.trade_date_max = _update_minmax_arrow(
        target.trade_date_min, target.trade_date_max, trade_date, regex=r"^\d{8}$"
    )
    target.trade_time_min, target.trade_time_max = _update_minmax_arrow(
        target.trade_time_min, target.trade_time_max, trade_time, regex=r"^\d{14}$"
    )
    file_cov.balance_min, file_cov.balance_max = _update_minmax_arrow(
        file_cov.balance_min, file_cov.balance_max, balance, regex=r"^\d{8}$"
    )
    file_cov.trade_date_min, file_cov.trade_date_max = _update_minmax_arrow(
        file_cov.trade_date_min, file_cov.trade_date_max, trade_date, regex=r"^\d{8}$"
    )
    file_cov.trade_time_min, file_cov.trade_time_max = _update_minmax_arrow(
        file_cov.trade_time_min, file_cov.trade_time_max, trade_time, regex=r"^\d{14}$"
    )

    for cov in (target, file_cov):
        _counter_update_arrow(cov.balance_counts, balance, regex=r"^\d{8}$")
        _counter_update_arrow(cov.trade_date_counts, trade_date, regex=r"^\d{8}$")
        _counter_update_arrow(cov.line_counts, _batch_col(batch, "LINE_ID"))
        _counter_update_arrow(cov.rcd_type_counts, _batch_col(batch, "RCD_TYPE"))
        _counter_update_arrow(cov.trade_flag_counts, _batch_col(batch, "TRADE_FLAG"))
        _counter_update_arrow(cov.money_counts, _batch_col(batch, "TRADE_MONEY"))

    station_arr = _batch_col(batch, "STATION_ID")
    vals = _filtered(station_arr, zero_invalid=True)
    if len(vals) > 0:
        for item in pc.value_counts(vals).to_pylist():
            station = item["values"]
            if station is None:
                continue
            station = str(station)
            count = int(item["counts"])
            target.qr_station_counts[station] += count
            file_cov.qr_station_counts[station] += count
            target.station_counts[station] += count
            file_cov.station_counts[station] += count
    _update_date_station_arrow(target, file_cov, balance, station_arr)


def _summarize_counter(counter: Counter[str], max_items: int = 10) -> str:
    return "; ".join(f"{k}:{v}" for k, v in counter.most_common(max_items))


def _date_ranges(dates: Iterable[str]) -> str:
    ordered = sorted(d for d in dates if DATE_RE.match(d))
    if not ordered:
        return ""
    ranges: list[tuple[str, str]] = []
    start = prev = ordered[0]
    for raw in ordered[1:]:
        prev_dt = datetime.strptime(prev, "%Y%m%d").date()
        cur_dt = datetime.strptime(raw, "%Y%m%d").date()
        if (cur_dt - prev_dt).days == 1:
            prev = raw
        else:
            ranges.append((start, prev))
            start = prev = raw
    ranges.append((start, prev))
    return "; ".join(
        _iso_date(a) if a == b else f"{_iso_date(a)} to {_iso_date(b)}" for a, b in ranges
    )


def _coverage_row(cov: Coverage) -> dict[str, object]:
    station_lines = sorted({_station_line(s) for s in cov.station_counts if _station_line(s)}, key=lambda x: int(x))
    return {
        "channel": cov.channel,
        "files": len(cov.files),
        "size_gb": round(cov.size_bytes / 1024**3, 3),
        "rows": cov.rows,
        "skipped_bad_rows": cov.skipped_rows,
        "file_periods": "; ".join(sorted(set(cov.file_periods))),
        "balance_date_min": cov.balance_min or "",
        "balance_date_max": cov.balance_max or "",
        "balance_date_min_iso": _iso_date(cov.balance_min),
        "balance_date_max_iso": _iso_date(cov.balance_max),
        "balance_days": len(cov.balance_counts),
        "balance_date_ranges": _date_ranges(cov.balance_counts.keys()),
        "trade_date_min": cov.trade_date_min or "",
        "trade_date_max": cov.trade_date_max or "",
        "trade_date_min_iso": _iso_date(cov.trade_date_min),
        "trade_date_max_iso": _iso_date(cov.trade_date_max),
        "trade_days": len(cov.trade_date_counts),
        "trade_date_ranges": _date_ranges(cov.trade_date_counts.keys()),
        "trade_time_min": cov.trade_time_min or "",
        "trade_time_max": cov.trade_time_max or "",
        "trade_time_min_iso": _iso_time(cov.trade_time_min),
        "trade_time_max_iso": _iso_time(cov.trade_time_max),
        "line_id_count": len(cov.line_counts),
        "line_ids": "|".join(sorted(cov.line_counts, key=lambda x: int(x) if x.isdigit() else 9999)),
        "station_code_count": len(cov.station_counts),
        "entry_station_code_count": len(cov.entry_station_counts),
        "exit_station_code_count": len(cov.exit_station_counts),
        "qr_station_code_count": len(cov.qr_station_counts),
        "station_line_count": len(station_lines),
        "station_lines_inferred_from_code": "|".join(station_lines),
        "top_trade_type": _summarize_counter(cov.trade_type_counts),
        "top_rcd_type": _summarize_counter(cov.rcd_type_counts),
        "top_money": _summarize_counter(cov.money_counts),
    }


def run(input_dir: Path, output_dir: Path, chunksize: int) -> None:
    files = sorted(p for p in input_dir.glob("*.csv") if _channel_from_name(p))
    if not files:
        raise FileNotFoundError(f"No AFC CSV files found under {input_dir}")

    by_channel = {channel: Coverage(channel) for channel in CHANNELS}
    file_coverages: list[Coverage] = []

    for path in files:
        channel = _channel_from_name(path)
        assert channel is not None
        cov = by_channel[channel]
        file_cov = Coverage(path.name)
        file_cov.size_bytes = path.stat().st_size
        cov.size_bytes += file_cov.size_bytes
        cov.files.append(str(path))
        start, end = _period_from_name(path)
        if start and end:
            period = f"{_iso_date(start)} to {_iso_date(end)}"
            cov.file_periods.append(period)
            file_cov.file_periods.append(period)

        usecols = QR_USECOLS if channel == "二维码" else CARD_USECOLS
        column_types = {col: "string" for col in usecols}
        process = _process_qr_batch if channel == "二维码" else _process_card_batch
        skipped = [0]

        def _skip_bad_row(_row) -> str:
            skipped[0] += 1
            return "skip"

        print(f"[SCAN] {path.name} ({file_cov.size_bytes / 1024**3:.2f} GB)", flush=True)
        reader = pv.open_csv(
            path,
            read_options=pv.ReadOptions(block_size=chunksize, encoding="utf8"),
            parse_options=pv.ParseOptions(invalid_row_handler=_skip_bad_row),
            convert_options=pv.ConvertOptions(
                include_columns=usecols,
                column_types=column_types,
                strings_can_be_null=True,
                null_values=["", "null", "NULL", "None", "none", "nan", "NaN"],
            ),
        )
        while True:
            try:
                batch = reader.read_next_batch()
            except StopIteration:
                break
            rows = batch.num_rows
            cov.rows += rows
            file_cov.rows += rows
            process(batch, cov, file_cov)
        cov.skipped_rows += skipped[0]
        file_cov.skipped_rows += skipped[0]
        if skipped[0]:
            print(f"[WARN] skipped malformed rows: {path.name} rows={skipped[0]}", flush=True)
        file_coverages.append(file_cov)

    output_dir.mkdir(parents=True, exist_ok=True)

    channel_summary = pd.DataFrame([_coverage_row(by_channel[c]) for c in CHANNELS])
    channel_summary.to_csv(output_dir / "afc_channel_summary.csv", index=False, encoding="utf-8-sig")

    file_summary = pd.DataFrame([_coverage_row(c) | {"file_name": c.channel} for c in file_coverages])
    cols = ["file_name"] + [c for c in file_summary.columns if c != "file_name"]
    file_summary[cols].to_csv(output_dir / "afc_file_summary.csv", index=False, encoding="utf-8-sig")

    daily_rows: list[dict[str, object]] = []
    trade_date_rows: list[dict[str, object]] = []
    station_rows: list[dict[str, object]] = []
    station_line_rows: list[dict[str, object]] = []
    matrix: dict[str, dict[str, object]] = {}

    for channel, cov in by_channel.items():
        for date, rows in sorted(cov.balance_counts.items()):
            daily_rows.append(
                {
                    "channel": channel,
                    "balance_date": date,
                    "balance_date_iso": _iso_date(date),
                    "rows": rows,
                    "unique_station_codes": len(cov.balance_date_stations.get(date, set())),
                }
            )
        for date, rows in sorted(cov.trade_date_counts.items()):
            trade_date_rows.append(
                {
                    "channel": channel,
                    "trade_date": date,
                    "trade_date_iso": _iso_date(date),
                    "rows": rows,
                }
            )

        station_line_sets: dict[str, set[str]] = defaultdict(set)
        for station, total in sorted(cov.station_counts.items(), key=lambda kv: (int(kv[0]) if kv[0].isdigit() else 999999, kv[0])):
            line = _station_line(station)
            station_line_sets[line].add(station)
            station_rows.append(
                {
                    "channel": channel,
                    "station_code": station,
                    "inferred_line_ref": line,
                    "total_mentions": total,
                    "entry_mentions": cov.entry_station_counts.get(station, 0),
                    "exit_mentions": cov.exit_station_counts.get(station, 0),
                    "qr_mentions": cov.qr_station_counts.get(station, 0),
                }
            )
            row = matrix.setdefault(
                station,
                {
                    "station_code": station,
                    "inferred_line_ref": line,
                    "长安通": 0,
                    "地铁票": 0,
                    "交通部一卡通": 0,
                    "二维码": 0,
                },
            )
            row[channel] = 1
        for line, stations in sorted(station_line_sets.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 9999):
            station_line_rows.append(
                {
                    "channel": channel,
                    "inferred_line_ref": line,
                    "unique_station_codes": len(stations),
                }
            )

    pd.DataFrame(daily_rows).to_csv(output_dir / "afc_channel_balance_date_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(trade_date_rows).to_csv(output_dir / "afc_channel_trade_date_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(station_rows).to_csv(output_dir / "afc_channel_station_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(station_line_rows).to_csv(output_dir / "afc_channel_station_line_coverage.csv", index=False, encoding="utf-8-sig")

    matrix_df = pd.DataFrame(matrix.values())
    matrix_df["channel_count"] = matrix_df[list(CHANNELS)].sum(axis=1)
    matrix_df = matrix_df.sort_values(
        ["inferred_line_ref", "station_code"],
        key=lambda s: s.map(lambda x: int(x) if str(x).isdigit() else 999999),
    )
    matrix_df.to_csv(output_dir / "afc_station_channel_matrix.csv", index=False, encoding="utf-8-sig")

    metadata = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "chunksize": chunksize,
        "channels": CHANNELS,
        "notes": [
            "Station coverage is based on AFC station codes, not the ODS physical station_id.",
            "For card channels, station coverage is union of ENTRY_STATION_ID and EXIT_STATION_ID excluding 0.",
            "For QR channel, station coverage uses STATION_ID excluding 0.",
            "Sensitive columns such as card/user/order ids are not read or exported.",
        ],
    }
    (output_dir / "afc_coverage_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[DONE] coverage outputs written to {output_dir}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/BaiduNetdiskDownload/运营数据/四"),
        help="Directory containing AFC CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/afc_coverage"),
        help="Directory for coverage CSV outputs.",
    )
    parser.add_argument("--chunksize", type=int, default=67_108_864, help="PyArrow CSV block size in bytes.")
    args = parser.parse_args()
    run(args.input_dir, args.output_dir, args.chunksize)


if __name__ == "__main__":
    main()
