"""
站点位置可视化（基于 ODS dim_station 坐标）。

输出: output/xian_station_map.html

默认仅展示站点点位，按 primary_line_ref 上色。
可选叠加指标（着色）：
  - baseline_mean_daily_total: Stage1 基线日均总客流（来自 data/analysis/baseline/station_baseline_metrics.csv）
  - matched_delta_pct: 增强匹配的站点客流偏离（来自 data/analysis/station_rain_matched_detail_v2_2025H1.csv）
  - matched_rrr: 增强匹配的站点客流保持率 RRR = sum(rain)/sum(baseline)

用法:
  python -m scripts.run_station_map
  python -m scripts.run_station_map --overlay baseline_mean_daily_total
  python -m scripts.run_station_map --overlay matched_delta_pct --metric total_count
  python -m scripts.run_station_map --overlay matched_rrr --metric total_count --time-group evening_offpeak --rain-grade rain_mid
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Ensure project root is on path (for scripts.ods imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.ods.ods_reader import ODS  # noqa: E402


DEFAULT_CENTER = (34.341, 108.940)
DEFAULT_ZOOM = 11.7
DEFAULT_TILE = (
    "https://webrd0{s}.is.autonavi.com/appmaptile?"
    "lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
)


def _fatal(msg: str) -> "None":
    raise SystemExit(msg)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        _fatal(f"[AUDIT][FATAL] missing file: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    return df


def _coerce_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def _quantile_color(val: float, breaks: list[float], palette: list[str]) -> str:
    # breaks length = len(palette)-1
    if math.isnan(val):
        return "#9aa0a6"  # gray for missing
    for i, b in enumerate(breaks):
        if val <= b:
            return palette[i]
    return palette[-1]


def _diverging_color(val: float, max_abs: float) -> str:
    """Blue (positive) — white — red (negative) around 0."""
    if math.isnan(val):
        return "#9aa0a6"
    if max_abs <= 0:
        return "#ffffff"
    x = max(-1.0, min(1.0, val / max_abs))
    # 9-class RdBu like (reversed so negative->red, positive->blue)
    palette = [
        "#b2182b",
        "#d6604d",
        "#f4a582",
        "#fddbc7",
        "#f7f7f7",
        "#d1e5f0",
        "#92c5de",
        "#4393c3",
        "#2166ac",
    ]
    # map [-1,1] -> [0,8]
    idx = int(round((x + 1) * 4))
    idx = max(0, min(8, idx))
    return palette[idx]


def _build_overlay(
    overlay: str,
    *,
    metric: str,
    time_group: Optional[str],
    rain_grade: Optional[str],
) -> tuple[pd.DataFrame, str]:
    """Return overlay df with columns: station_name, value, plus label."""
    overlay = overlay.strip()
    if overlay == "baseline_mean_daily_total":
        path = Path("data/analysis/baseline/station_baseline_metrics.csv")
        df = _read_csv(path)
        if "station_name" not in df.columns or "mean_daily_total" not in df.columns:
            _fatal(f"[AUDIT][FATAL] baseline csv schema unexpected: {path}")
        out = df[["station_name", "mean_daily_total"]].copy()
        out = out.rename(columns={"mean_daily_total": "value"})
        label = "Baseline mean daily total (normal weather days)"
        return out, label

    if overlay in ("matched_delta_pct", "matched_rrr"):
        path = Path("data/analysis/station_rain_matched_detail_v2_2025H1.csv")
        df = _read_csv(path)
        required = {"station_name", "metric", "rain_value", "baseline_value"}
        if not required.issubset(set(df.columns)):
            _fatal(f"[AUDIT][FATAL] matched detail schema unexpected: {path}")

        df = df[df["metric"] == metric].copy()
        if time_group is not None:
            df = df[df["time_group"] == time_group].copy()
        if rain_grade is not None:
            df = df[df["precip_quantile_grade"] == rain_grade].copy()

        df["rain_value"] = pd.to_numeric(df["rain_value"], errors="coerce").fillna(0.0)
        df["baseline_value"] = pd.to_numeric(df["baseline_value"], errors="coerce").fillna(0.0)

        g = (
            df.groupby("station_name", observed=True)
            .agg(
                rain_sum=("rain_value", "sum"),
                base_sum=("baseline_value", "sum"),
                n=("baseline_value", "size"),
            )
            .reset_index()
        )

        # Avoid division by zero
        g["rrr"] = g.apply(
            lambda r: (r["rain_sum"] / r["base_sum"]) if r["base_sum"] > 0 else float("nan"),
            axis=1,
        )
        g["delta_pct"] = g.apply(
            lambda r: ((r["rain_sum"] - r["base_sum"]) / r["base_sum"])
            if r["base_sum"] > 0
            else float("nan"),
            axis=1,
        )

        if overlay == "matched_rrr":
            out = g[["station_name", "rrr", "n"]].rename(columns={"rrr": "value"})
            label = f"Matched RRR (metric={metric})"
        else:
            out = g[["station_name", "delta_pct", "n"]].rename(columns={"delta_pct": "value"})
            label = f"Matched delta_pct (metric={metric})"
        return out, label

    _fatal(f"[AUDIT][FATAL] unknown overlay: {overlay}")


HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>西安地铁站点地图</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#111;font-family:'PingFang SC','Microsoft YaHei',sans-serif}}
#map{{width:100vw;height:100vh}}
.leaflet-tile-pane{{
  filter:grayscale(100%) saturate(0) brightness(1.08) contrast(0.92);
}}
#title{{
  position:fixed;top:16px;left:50%;transform:translateX(-50%);
  z-index:1000;background:rgba(15,20,30,0.90);border:1px solid #2a3a4a;
  border-radius:12px;padding:10px 22px;color:#fff;text-align:center;
  backdrop-filter:blur(10px);pointer-events:none;max-width:min(92vw,880px);
}}
#title h1{{font-size:18px;font-weight:700;letter-spacing:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#title p{{font-size:11px;color:#7a9ab0;margin-top:3px;line-height:1.2}}
#legend{{
  position:fixed;bottom:24px;left:16px;z-index:1000;
  background:rgba(15,20,30,0.90);border:1px solid #2a3a4a;
  border-radius:12px;padding:12px 14px;color:#ddd;
  backdrop-filter:blur(10px);max-height:60vh;overflow:auto;
}}
#legend h3{{font-size:11px;color:#7a9ab0;margin-bottom:8px;letter-spacing:1px}}
.leg{{display:flex;align-items:center;margin:4px 0;font-size:12px}}
.dot{{width:12px;height:12px;border-radius:50%;margin-right:8px;flex-shrink:0}}
</style>
</head>
<body>
<div id="title">
  <h1>西安地铁站点地图</h1>
  <p>{subtitle}</p>
</div>
<div id="map"></div>
<div id="legend">
  <h3>LEGEND</h3>
  {legend_html}
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const STATIONS={stations_json};
const map=L.map('map',{{center:[{center_lat},{center_lon}],zoom:{zoom}}});

L.tileLayer(
  '{tile_url}',
  {{subdomains:'1234',attribution:'&copy; 高德地图',maxZoom:19,opacity:0.82}}
).addTo(map);

STATIONS.forEach(st=>{{
  if (st.lat == null || st.lon == null) return;
  L.circleMarker([st.lat,st.lon],{{
    radius:5,color:'#fff',weight:1.5,
    fillColor:st.color,fillOpacity:0.96
  }})
  .bindPopup(`<b>${{st.name}}</b>`
    + (st.lines ? `<br/>${{st.lines}}` : '')
    + (st.value_label ? `<br/><span style="color:#7a9ab0">${{st.value_label}}</span>` : '')
  )
  .bindTooltip(st.name,{{direction:'top',offset:[0,-6]}})
  .addTo(map);
}});
</script>
</body>
</html>
"""


def _legend_for_lines(df_station: pd.DataFrame) -> str:
    # Stable line colors (deterministic)
    refs = sorted({str(x) for x in df_station["primary_line_ref"].dropna().unique()})
    # muted but distinct palette
    palette = [
        "#6aaed6",
        "#f28e2b",
        "#59a14f",
        "#e15759",
        "#b07aa1",
        "#edc949",
        "#76b7b2",
        "#ff9da7",
        "#9c755f",
        "#bab0ac",
    ]
    colors = {ref: palette[i % len(palette)] for i, ref in enumerate(refs)}
    legend = "".join(
        f'<div class="leg"><div class="dot" style="background:{colors[ref]}"></div>Line {ref}</div>'
        for ref in refs
    )
    return legend, colors


def main() -> None:
    parser = argparse.ArgumentParser(description="Station map visualization.")
    parser.add_argument(
        "--overlay",
        default="none",
        help="Overlay metric: none | baseline_mean_daily_total | matched_delta_pct | matched_rrr",
    )
    parser.add_argument(
        "--metric",
        default="total_count",
        help="For matched overlays: entry_count | exit_count | total_count",
    )
    parser.add_argument(
        "--time-group",
        default=None,
        help="Filter matched detail by time_group (morning_peak/evening_peak/daytime_offpeak/evening_offpeak/night).",
    )
    parser.add_argument(
        "--rain-grade",
        default=None,
        help="Filter matched detail by precip_quantile_grade (rain_low/rain_mid/rain_high).",
    )
    parser.add_argument("--out", default="output/xian_station_map.html")
    parser.add_argument("--center-lat", type=float, default=DEFAULT_CENTER[0])
    parser.add_argument("--center-lon", type=float, default=DEFAULT_CENTER[1])
    parser.add_argument("--zoom", type=float, default=DEFAULT_ZOOM)
    args = parser.parse_args()

    df_station = ODS.dim_station().copy()
    df_station = df_station[df_station["has_coords"] == True].copy()  # noqa: E712

    legend_html, line_colors = _legend_for_lines(df_station)

    overlay = args.overlay.strip().lower()
    overlay_df = None
    overlay_label = ""
    if overlay != "none":
        overlay_df, overlay_label = _build_overlay(
            overlay,
            metric=args.metric,
            time_group=args.time_group,
            rain_grade=args.rain_grade,
        )
        overlay_df["station_name"] = overlay_df["station_name"].astype(str)
        overlay_df["value"] = overlay_df["value"].apply(_coerce_float)

        df_station = df_station.merge(
            overlay_df[["station_name", "value"]], on="station_name", how="left"
        )

        # For overlay mode, legend switches to a simple numeric legend
        legend_html = (
            '<div style="font-size:12px;line-height:1.35;color:#cfd8dc;max-width:260px">'
            f'<div style="margin-bottom:6px;color:#7a9ab0">{overlay_label}</div>'
            "<div>color: value scale</div>"
            "</div>"
        )

    stations_json = []
    missing_coords = 0
    for _, r in df_station.iterrows():
        lat = r.get("lat")
        lon = r.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            missing_coords += 1
            continue

        line_ref = str(r.get("primary_line_ref") or "")
        color = line_colors.get(line_ref, "#aaaaaa")
        value = r.get("value") if overlay != "none" else None
        value_label = ""
        if overlay != "none":
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                value_label = f"value={value:.4f}"
            # Color by overlay value
            if overlay == "baseline_mean_daily_total":
                # sequential palette on log scale
                palette = [
                    "#fff5eb",
                    "#fee6ce",
                    "#fdd0a2",
                    "#fdae6b",
                    "#fd8d3c",
                    "#f16913",
                    "#d94801",
                    "#a63603",
                    "#7f2704",
                ]
                v = (
                    math.log1p(value)
                    if value is not None and not math.isnan(value)
                    else float("nan")
                )
                # breaks on quantiles of log1p(value)
                vals = df_station["value"].dropna().apply(lambda x: math.log1p(float(x))).values
                if len(vals) > 0:
                    q = pd.Series(vals).quantile([0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]).tolist()
                    color = _quantile_color(v, q, palette)
            else:
                # diverging around 0
                series = df_station["value"].dropna().astype(float)
                max_abs = float(series.abs().max()) if len(series) else 0.0
                color = _diverging_color(
                    float(value) if value is not None else float("nan"), max_abs=max_abs
                )

        stations_json.append(
            {
                "name": str(r.get("display_name") or r.get("station_name") or ""),
                "lat": float(lat),
                "lon": float(lon),
                "lines": str(r.get("line_refs") or ""),
                "color": color,
                "value_label": value_label,
            }
        )

    subtitle = f"stations={len(stations_json)} (missing_coords={missing_coords})"
    if overlay != "none":
        subtitle += f" | overlay={overlay} metric={args.metric}"
        if args.time_group:
            subtitle += f" time_group={args.time_group}"
        if args.rain_grade:
            subtitle += f" rain_grade={args.rain_grade}"

    html = HTML.format(
        subtitle=subtitle,
        legend_html=legend_html,
        stations_json=json.dumps(stations_json, ensure_ascii=False),
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        zoom=args.zoom,
        tile_url=DEFAULT_TILE,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[AUDIT] station map written: {out} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
