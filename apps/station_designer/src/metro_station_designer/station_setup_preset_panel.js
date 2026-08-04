import React from "react";

import { recordDebugEvent } from "./debug_event_log.js?v=debug-log-1";
import { STATION_SETUP_PRESETS } from "./station_setup_presets.js?v=station-presets-1";

const h = React.createElement;

export function StationSetupPresetPanel({ disabled, onSelect }) {
  return h("section", { className: "setup-presets", "aria-label": "一键站点模板" }, [
    h("div", { key: "head", className: "setup-presets__head" }, [
      h("strong", { key: "title" }, "一键模板"),
      h("span", { key: "hint" }, "直接生成，进入后仍可拖动修改"),
    ]),
    h("div", { key: "grid", className: "setup-presets__grid" },
      STATION_SETUP_PRESETS.map((preset) =>
        h("button", {
          key: preset.id,
          className: "setup-preset",
          disabled,
          onClick: () => {
            recordDebugEvent("setup.preset_selected", {
              preset_id: preset.id,
              config: preset.config,
            });
            onSelect(preset);
          },
          "data-testid": `station-preset-${preset.id}`,
        }, [
          h("span", { key: "levels", className: "setup-preset__levels" },
            `${preset.config.levels} 层 · ${preset.config.isTransfer ? "换乘" : "普通"}`,
          ),
          h("strong", { key: "label" }, preset.label),
          h("small", { key: "description" }, preset.description),
          h("span", { key: "counts", className: "setup-preset__counts" },
            `${preset.config.entranceCount} 口 · ${preset.config.gateCount} 闸机`,
          ),
        ]),
      ),
    ),
    h("div", { key: "divider", className: "setup-presets__divider" }, "或者自定义"),
  ]);
}
