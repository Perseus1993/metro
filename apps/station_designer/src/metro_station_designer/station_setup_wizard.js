import React, { useEffect, useMemo, useState } from "react";

import { recordDebugEvent } from "./debug_event_log.js?v=debug-log-1";
import {
  STATION_SETUP_LIMITS,
  stationSetupCounts,
} from "./station_setup.js?v=station-setup-1";
import { StationSetupPresetPanel } from "./station_setup_preset_panel.js?v=station-presets-1";

const h = React.createElement;
const DEFAULT_COUNTS = { entranceCount: 2, gateCount: 4 };

export function StationSetupWizard({ allowCancel, catalogReady, onCancel, onStart, open }) {
  const [step, setStep] = useState(0);
  const [levels, setLevels] = useState(null);
  const [isTransfer, setIsTransfer] = useState(null);
  const [entranceCount, setEntranceCount] = useState(DEFAULT_COUNTS.entranceCount);
  const [gateCount, setGateCount] = useState(DEFAULT_COUNTS.gateCount);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setLevels(null);
    setIsTransfer(null);
    setEntranceCount(DEFAULT_COUNTS.entranceCount);
    setGateCount(DEFAULT_COUNTS.gateCount);
    recordDebugEvent("setup.opened", { allow_cancel: Boolean(allowCancel) });
  }, [allowCancel, open]);

  const config = useMemo(
    () => ({ levels, isTransfer, entranceCount, gateCount }),
    [entranceCount, gateCount, isTransfer, levels],
  );
  const canContinue = step === 0 ? levels !== null : isTransfer !== null;

  if (!open) return null;

  return h("div", { className: "setup-overlay", "data-testid": "station-setup-wizard" }, [
    h("section", { key: "dialog", className: "setup-dialog", role: "dialog", "aria-modal": true }, [
      h("header", { key: "head", className: "setup-dialog__head" }, [
        h("div", { key: "copy" }, [
          h("span", { key: "eyebrow", className: "setup-dialog__eyebrow" }, "新建站点"),
          h("h1", { key: "title" }, wizardTitle(step)),
          h("p", { key: "desc" }, wizardDescription(step)),
        ]),
        allowCancel
          ? h("button", {
              key: "close",
              className: "setup-close",
              onClick: () => {
                recordDebugEvent("setup.cancelled", { step });
                onCancel();
              },
            }, "取消")
          : null,
      ]),
      h(StepRail, { key: "rail", current: step }),
      h("div", { key: "body", className: "setup-dialog__body" },
        step === 0
          ? h(SetupStartStep, {
              catalogReady,
              levels,
              onPresetSelect: (preset) => {
                recordDebugEvent("setup.submitted", {
                  config: preset.config,
                  preset_id: preset.id,
                });
                onStart(preset.config);
              },
              setLevels,
            })
          : step === 1
            ? h(StationTypeStep, { isTransfer, setIsTransfer })
            : h(QuantityStep, { entranceCount, gateCount, setEntranceCount, setGateCount }),
      ),
      step === 2 ? h(SetupSummary, { key: "summary", config }) : null,
      h("footer", { key: "footer", className: "setup-dialog__footer" }, [
        step > 0
          ? h("button", {
              key: "back",
              className: "button",
              onClick: () => {
                recordDebugEvent("setup.previous_step", { from_step: step, to_step: step - 1 });
                setStep(step - 1);
              },
            }, "上一步")
          : h("span", { key: "spacer" }),
        step < 2
          ? h("button", {
              key: "next",
              className: "button button--primary setup-next",
              disabled: !canContinue,
              onClick: () => {
                recordDebugEvent("setup.next_step", { from_step: step, to_step: step + 1 });
                setStep(step + 1);
              },
              "data-testid": "station-setup-next",
            }, "下一步")
          : h("button", {
              key: "start",
              className: "button button--primary setup-next",
              disabled: !catalogReady,
              onClick: () => {
                recordDebugEvent("setup.submitted", { config });
                onStart(config);
              },
              "data-testid": "station-setup-start",
            }, catalogReady ? "自动布置并进入编辑器" : "正在加载设施…"),
      ]),
    ]),
  ]);
}

function SetupStartStep({ catalogReady, levels, onPresetSelect, setLevels }) {
  return h("div", { className: "setup-start" }, [
    h(StationSetupPresetPanel, {
      key: "presets",
      disabled: !catalogReady,
      onSelect: onPresetSelect,
    }),
    h(LevelStep, { key: "levels", levels, setLevels }),
  ]);
}

function StepRail({ current }) {
  const labels = ["选楼层", "选站型", "选数量"];
  return h("ol", { className: "setup-rail" }, labels.map((label, index) =>
    h("li", { key: label, className: index <= current ? "setup-rail__item setup-rail__item--active" : "setup-rail__item" }, [
      h("span", { key: "number" }, String(index + 1)),
      h("b", { key: "label" }, label),
    ]),
  ));
}

function LevelStep({ levels, setLevels }) {
  return h("div", { className: "setup-choice-grid setup-choice-grid--three" }, [1, 2, 3].map((count) =>
    h(ChoiceButton, {
      key: count,
      active: levels === count,
      detail: count === 1 ? "站厅与月台同层" : `${count - 1} 个跨层区段`,
      label: `${count} 层站`,
      onClick: () => {
        recordDebugEvent("setup.level_selected", { levels: count });
        setLevels(count);
      },
      testId: `station-level-${count}`,
    }),
  ));
}

function StationTypeStep({ isTransfer, setIsTransfer }) {
  return h("div", { className: "setup-choice-grid" }, [
    h(ChoiceButton, {
      key: "normal", active: isTransfer === false, label: "普通站", detail: "自动放置 1 条线路月台",
      onClick: () => {
        recordDebugEvent("setup.station_type_selected", { is_transfer: false });
        setIsTransfer(false);
      }, testId: "station-type-normal",
    }),
    h(ChoiceButton, {
      key: "transfer", active: isTransfer === true, label: "换乘站", detail: "自动放置 2 条不同线路月台",
      onClick: () => {
        recordDebugEvent("setup.station_type_selected", { is_transfer: true });
        setIsTransfer(true);
      }, testId: "station-type-transfer",
    }),
  ]);
}

function ChoiceButton({ active, detail, label, onClick, testId }) {
  return h("button", {
    className: active ? "setup-choice setup-choice--active" : "setup-choice",
    onClick,
    "data-testid": testId,
  }, [h("strong", { key: "label" }, label), h("span", { key: "detail" }, detail)]);
}

function QuantityStep({ entranceCount, gateCount, setEntranceCount, setGateCount }) {
  return h("div", { className: "setup-quantities" }, [
    h(Stepper, {
      key: "entrances", label: "地铁口数量", value: entranceCount,
      limits: STATION_SETUP_LIMITS.entrances,
      onChange: (value) => {
        recordDebugEvent("setup.entrance_count_changed", { from: entranceCount, to: value });
        setEntranceCount(value);
      },
    }),
    h(Stepper, {
      key: "gates", label: "闸机总数", value: gateCount,
      limits: STATION_SETUP_LIMITS.gates,
      onChange: (value) => {
        recordDebugEvent("setup.gate_count_changed", { from: gateCount, to: value });
        setGateCount(value);
      },
    }),
    h("p", { key: "hint", className: "setup-quantity-hint" },
      "闸机会自动均分为进站和出站；总数为奇数时，进站闸机多 1 台。",
    ),
  ]);
}

function Stepper({ label, limits, onChange, value }) {
  return h("div", { className: "setup-stepper" }, [
    h("div", { key: "label", className: "setup-stepper__label" }, [
      h("strong", { key: "name" }, label),
      h("small", { key: "range" }, `允许 ${limits.min}–${limits.max}`),
    ]),
    h("div", { key: "control", className: "setup-stepper__control" }, [
      h("button", { key: "minus", disabled: value <= limits.min, onClick: () => onChange(value - 1) }, "−"),
      h("output", { key: "value" }, String(value)),
      h("button", { key: "plus", disabled: value >= limits.max, onClick: () => onChange(value + 1) }, "+"),
    ]),
  ]);
}

function SetupSummary({ config }) {
  const counts = stationSetupCounts(config);
  return h("div", { className: "setup-summary" }, [
    h("strong", { key: "title" }, "将自动放置"),
    h("span", { key: "copy" },
      `${counts.entrances} 个地铁口 · ${counts.entryGates} 台进站闸机 · ${counts.exitGates} 台出站闸机 · ${counts.platforms} 个月台` +
      (config.levels > 1
        ? ` · ${counts.downEscalators + counts.upEscalators} 组扶梯 · ${counts.stairs} 组楼梯 · 1 部直梯`
        : ""),
    ),
  ]);
}

function wizardTitle(step) {
  return ["选择模板，或自己配置", "这是换乘站吗？", "需要多少出入口和闸机？"][step];
}

function wizardDescription(step) {
  return [
    "一键模板可以直接进入编辑器；自定义时先确定楼层结构。",
    "换乘站会自动创建两条线路的月台，后面可继续微调。",
    "系统先给出可运行的基础布局，进入画布后每个设施都能拖动。",
  ][step];
}
