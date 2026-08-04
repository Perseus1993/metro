import React from "react";

import { beginComponentDrag } from "./component_palette.js?v=guided-builder-1";
import { beginDemandFlowDrag } from "./demand_flow_palette.js?v=guided-builder-1";

const h = React.createElement;

export function ComponentGrid({ components, onAddComponent }) {
  return h(
    "div",
    { className: "palette-grid" },
    components.map((component) =>
      h(ComponentCard, { key: component.id, component, onAddComponent }),
    ),
  );
}

export function FlowCard({ flow, onAddDemandFlow }) {
  return h(
    "button",
    {
      "data-testid": `palette-flow-${flow.id}`,
      className: `flow-palette__item flow-palette__item--${flow.intent}`,
      draggable: true,
      onClick: () => onAddDemandFlow(flow),
      onDragStart: (event) => beginDemandFlowDrag(event, flow),
      title: "点击自动绑定；也可拖到对应入口或月台",
    },
    [
      h("span", { key: "icon", className: "flow-palette__icon" }, "→"),
      h("span", { key: "label" }, flowLabel(flow.intent)),
      h("span", { key: "action", className: "flow-palette__action" }, "点绑定 · 可拖动"),
    ],
  );
}

function ComponentCard({ component, onAddComponent }) {
  return h(
    "button",
    {
      "aria-label": `${componentLabel(component)}，点击自动放置或拖到画布`,
      "data-testid": `palette-component-${component.id}`,
      className: `palette-item palette-item--${component.kind}`,
      draggable: true,
      onClick: () => onAddComponent(component),
      onDragStart: (event) => beginComponentDrag(event, component),
      title: "点击自动放置；按住可拖到画布指定位置",
    },
    [
      h("span", { key: "icon", className: "palette-item__icon" }, componentCode(component)),
      h("span", { key: "label", className: "palette-item__label" }, componentLabel(component)),
      h("span", { key: "action", className: "palette-item__action" }, "点放置 · 可拖动"),
    ],
  );
}

function componentLabel(component) {
  return {
    entrance: "入口",
    entry_gate: "进站闸机",
    exit_gate: "出站闸机",
    bidirectional_gate: "双向闸机",
    platform_edge: "月台 L1",
    platform_edge_l2_up: "月台 L2",
    down_escalator: "下行扶梯",
    up_escalator: "上行扶梯",
    stairs: "楼梯",
    elevator: "直梯",
    equipment: "设备",
    shop: "商铺",
    obstacle: "障碍物",
  }[component.id] || component.label;
}

function flowLabel(intent) {
  return {
    enter_and_board: "进站上车客流",
    exit_station: "下车出站客流",
    transfer: "站内换乘客流",
  }[intent] || intent;
}

function componentCode(component) {
  if (component.kind === "entrance") return "入";
  if (component.kind === "gate") return "闸";
  if (component.kind === "platform_edge") return "台";
  if (component.kind === "escalator") return "扶";
  if (component.kind === "stairs") return "梯";
  if (component.kind === "elevator") return "直";
  if (component.kind === "shop") return "店";
  if (component.kind === "obstacle") return "障";
  return "设";
}
