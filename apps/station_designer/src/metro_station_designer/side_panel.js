import React from "react";

import { ComponentGrid, FlowCard } from "./guided_palette_cards.js?v=guided-builder-1";

const h = React.createElement;
const OPTIONAL_COMPONENTS = new Set(["equipment", "shop", "obstacle"]);

export function LeftPanel({
  buildProgress,
  catalog,
  onAddComponent,
  onAddDemandFlow,
  onNewStation,
  stationSetup,
  templateId,
}) {
  const components = catalog?.component_palette || [];
  const primaryComponents = components.filter((component) => !OPTIONAL_COMPONENTS.has(component.kind));
  const optionalComponents = components.filter((component) => OPTIONAL_COMPONENTS.has(component.kind));

  return h("aside", { className: "side" }, [
    h(CurrentStationSection, {
      key: "templates",
      onNewStation,
      stationSetup,
      templateId,
    }),
    buildProgress?.isScratch
      ? h(BuildProgress, { key: "progress", progress: buildProgress })
      : null,
    h("section", { key: "palette", className: "section section--guided" }, [
      h("h2", { key: "title", className: "section__title" }, "1 微调或补充设施"),
      h(
        "div",
        { key: "hint", className: "guided-hint" },
        "基础设施已经自动放好。需要补充时直接点卡片；已有设施可在画布上拖动微调。",
      ),
      h(ComponentGrid, {
        key: "primary",
        components: primaryComponents,
        onAddComponent,
      }),
      optionalComponents.length
        ? h("details", { key: "optional", className: "side-details" }, [
            h("summary", { key: "summary" }, "可选设施与障碍物"),
            h(ComponentGrid, {
              key: "grid",
              components: optionalComponents,
              onAddComponent,
            }),
          ])
        : null,
    ]),
    h("section", { key: "flows", className: "section section--guided" }, [
      h("h2", { key: "title", className: "section__title" }, "3 定义客流"),
      h(
        "div",
        { key: "hint", className: "guided-hint" },
        "直接点客流卡即可自动绑定；也可拖到入口或月台上。",
      ),
      h(
        "div",
        { key: "grid", className: "flow-palette" },
        (catalog?.passenger_flow_palette || []).map((flow) =>
          h(FlowCard, { key: flow.id, flow, onAddDemandFlow }),
        ),
      ),
    ]),
    h(ReferenceDetails, { key: "refs", references: catalog?.reference_wheels || [] }),
  ]);
}

function CurrentStationSection({ onNewStation, stationSetup, templateId }) {
  return h("section", { className: "section section--guided" }, [
    h("h2", { key: "title", className: "section__title" }, "0 当前站点"),
    h("div", { key: "summary", className: "station-setup-card" }, [
      h("strong", { key: "type" }, stationSetup
        ? `${stationSetup.levels} 层${stationSetup.isTransfer ? "换乘站" : "普通站"}`
        : templateLabel(templateId)),
      h("span", { key: "counts" }, stationSetup
        ? `${stationSetup.entranceCount} 个地铁口 · ${stationSetup.gateCount} 台闸机`
        : "请通过建站向导配置"),
    ]),
    h("button", {
      key: "configure",
      className: "button station-setup-card__button",
      onClick: onNewStation,
    }, "重新选择楼层、站型和数量"),
  ]);
}

function BuildProgress({ progress }) {
  return h("section", { className: "section build-progress" }, [
    h("h2", { key: "title", className: "section__title" }, "建站进度"),
    h(
      "div",
      { key: "items", className: "build-progress__items" },
      progress.items.map((item) =>
        h("div", { key: item.id, className: item.complete ? "build-step build-step--done" : "build-step" }, [
          h("span", { key: "icon", className: "build-step__icon" }, item.complete ? "✓" : "○"),
          h("span", { key: "label" }, item.label),
        ]),
      ),
    ),
    h("div", { key: "next", className: "next-step" }, [
      h("strong", { key: "title" }, progress.next.title),
      h("span", { key: "text" }, progress.next.instruction),
    ]),
  ]);
}

function ReferenceDetails({ references }) {
  return h("details", { className: "section side-details side-details--references" }, [
    h("summary", { key: "summary" }, "技术参考"),
    ...references.map((wheel) =>
      h("div", { key: wheel.name, className: "reference-row" }, [
        h("div", { key: "name", className: "reference-row__name" }, wheel.name),
        h("div", { key: "repo", className: "reference-row__repo" }, wheel.repo),
      ]),
    ),
  ]);
}

function templateLabel(templateId) {
  return {
    scratch_single_level: "单层空白站",
    scratch_two_level: "二层空白站",
    scratch_three_level: "三层空白站",
  }[templateId] || templateId;
}
