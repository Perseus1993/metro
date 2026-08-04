"""
生成西安地铁线网地图 HTML（全高德方案）。

用法: python -m scripts.run_visualize
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metro_data_warehouse.amap_network import (
    build_amap_line_geometries,
    build_amap_station_and_line_catalog,
    get_amap_key,
    load_amap_subway_data,
    write_amap_station_csv,
)

DEFAULT_COLOR = "#AAAAAA"

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>西安地铁线网（全高德）</title>
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
  border-radius:12px;padding:10px 28px;color:#fff;text-align:center;
  backdrop-filter:blur(10px);pointer-events:none;
}}
#title h1{{font-size:19px;font-weight:700;letter-spacing:3px}}
#title p{{font-size:11px;color:#7a9ab0;margin-top:3px}}
#legend{{
  position:fixed;bottom:24px;left:16px;z-index:1000;
  background:rgba(15,20,30,0.90);border:1px solid #2a3a4a;
  border-radius:12px;padding:14px 18px;color:#ddd;
  backdrop-filter:blur(10px);max-height:60vh;overflow:auto;
}}
#legend h3{{font-size:11px;color:#7a9ab0;margin-bottom:8px;letter-spacing:1px}}
.leg{{display:flex;align-items:center;margin:4px 0;font-size:12px}}
.dot{{width:12px;height:12px;border-radius:50%;margin-right:8px;flex-shrink:0}}
</style>
</head>
<body>
<div id="title">
  <h1>西安地铁线网</h1>
  <p>AMap Subway Data &nbsp;|&nbsp; {n_stations} 站 &nbsp;·&nbsp; {n_lines} 条线路</p>
</div>
<div id="map"></div>
<div id="legend">
  <h3>LINE LEGEND</h3>
  {legend_html}
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const STATIONS={stations_json};
const LINES={lines_json};
const COLORS={colors_json};

const map=L.map('map',{{center:[34.341,108.940],zoom:11.7}});

L.tileLayer(
  'https://webrd0{{s}}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={{x}}&y={{y}}&z={{z}}',
  {{subdomains:'1234',attribution:'&copy; 高德地图',maxZoom:19,opacity:0.82}}
).addTo(map);

LINES.forEach(line=>{{
  (line.segments || []).forEach(seg=>{{
    if (!seg || seg.length < 2) return;
    L.polyline(seg,{{color:line.color,weight:4.5,opacity:0.95}})
     .bindTooltip(line.name,{{sticky:true}})
     .addTo(map);
  }});
}});

STATIONS.forEach(st=>{{
  const color=COLORS[st.line]||'{default_color}';
  L.circleMarker([st.lat,st.lon],{{
    radius:5,color:'#fff',weight:1.5,
    fillColor:color,fillOpacity:0.96
  }})
  .bindPopup(`<b>${{st.name}}</b>${{st.lines ? `<br/>${{st.lines}}` : ''}}`)
  .bindTooltip(st.name,{{direction:'top',offset:[0,-6]}})
  .addTo(map);
}});
</script>
</body>
</html>
"""


def build_legend(lines):
    return "".join(
        f'<div class="leg"><div class="dot" style="background:{line["color"]}"></div>{line["display_name"]}</div>'
        for line in lines
    )


def main():
    amap_key = get_amap_key()
    raw_data = load_amap_subway_data(refresh=False)
    stations, raw_lines = build_amap_station_and_line_catalog(raw_data)
    print(f"高德地铁图站点: {len(stations)}")
    print(f"高德地铁图线路: {len(raw_lines)}")

    lines = build_amap_line_geometries(raw_lines, amap_key)
    print("线路几何已拼接完成")

    station_csv_path = "output/xian_metro_stations_amap_subway.csv"
    write_amap_station_csv(station_csv_path, stations)
    print(f"站点已保存: {station_csv_path}")

    map_stations = [
        {
            "name": station["display_name"],
            "lat": station["lat"],
            "lon": station["lon"],
            "line": station["primary_line_ref"],
            "lines": " / ".join(station["line_labels"]),
            "source": station["source"],
        }
        for station in stations
    ]

    line_colors = {line["ref"]: line["color"] for line in lines}
    html = HTML.format(
        n_stations=len(map_stations),
        n_lines=len(lines),
        stations_json=json.dumps(map_stations, ensure_ascii=False),
        lines_json=json.dumps(lines, ensure_ascii=False),
        colors_json=json.dumps(line_colors, ensure_ascii=False),
        legend_html=build_legend(lines),
        default_color=DEFAULT_COLOR,
    )

    out = "output/xian_metro_map.html"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"地图已生成: {out}  ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
