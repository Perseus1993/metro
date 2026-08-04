import React from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
} from "@xyflow/react";

import { miniMapColor, nodeTypes } from "./flow_nodes.js?v=flexible-layout-1";
import { CanvasStatus } from "./status.js?v=ops-config-1";

const h = React.createElement;
const CANVAS_MODES = [
  { id: "overview", label: "布局" },
  { id: "queues", label: "队列" },
  { id: "connections", label: "连接" },
];

export function Canvas({
  buildProgress,
  canvasMode,
  compiling,
  displayEdges,
  displayNodes,
  error,
  isValidConnection,
  loading,
  notice,
  onConnect,
  onCanvasDragOver,
  onCanvasDrop,
  onEdgesChange,
  onNodesChange,
  onSelectionChange,
  payload,
  setCanvasMode,
  templateId,
}) {
  const shellClassName = ["canvas-shell", `canvas-shell--${canvasMode}`].join(" ");
  return h("main", { className: shellClassName, "data-testid": "station-canvas" }, [
    h(ReactFlow, {
      key: templateId,
      nodes: displayNodes,
      edges: displayEdges,
      nodeTypes,
      onNodesChange,
      onEdgesChange,
      onConnect,
      onDragOver: onCanvasDragOver,
      onDrop: onCanvasDrop,
      onSelectionChange,
      isValidConnection,
      connectionMode: "loose",
      nodesDraggable: true,
      nodesConnectable: canvasMode === "connections",
      elementsSelectable: true,
      selectNodesOnDrag: false,
      panOnDrag: [1, 2],
      nodeDragThreshold: 1,
      fitView: true,
      fitViewOptions: { padding: 0.24, maxZoom: 3.2 },
      minZoom: 0.2,
      maxZoom: 6,
      defaultViewport: payload?.react_flow?.viewport || { x: 0, y: 0, zoom: 1 },
      deleteKeyCode: ["Backspace", "Delete"],
      snapToGrid: true,
      snapGrid: [0.5, 0.5],
      children: [
        h(Background, { key: "bg", gap: 12, size: 1, color: "#d6cec1" }),
        h(Controls, { key: "controls", showInteractive: false }),
        h(MiniMap, {
          key: "mini",
          pannable: true,
          zoomable: true,
          nodeStrokeWidth: 2,
          nodeColor: (node) => miniMapColor(node),
        }),
      ],
    }),
    buildProgress?.isScratch
      ? h("div", { key: "guide", className: "canvas-guide" }, [
          h("strong", { key: "title" }, buildProgress.next.title),
          h("span", { key: "text" }, buildProgress.next.instruction),
          h("small", { key: "hint" }, "设施必须放在楼层矩形内；滚轮缩放，拖动画布空白处平移。"),
        ])
      : null,
    h(CanvasModeSwitch, { key: "mode", canvasMode, setCanvasMode }),
    h(CanvasStatus, { key: "canvas-status", compiling, error, loading, notice }),
  ]);
}

function CanvasModeSwitch({ canvasMode, setCanvasMode }) {
  return h(
    "div",
    { className: "canvas-mode-switch", role: "toolbar", "aria-label": "Canvas mode" },
    CANVAS_MODES.map((mode) =>
      h(
        "button",
        {
          key: mode.id,
          type: "button",
          className: [
            "canvas-mode-switch__button",
            canvasMode === mode.id ? "canvas-mode-switch__button--active" : "",
          ].join(" "),
          onClick: () => setCanvasMode(mode.id),
        },
        mode.label,
      ),
    ),
  );
}
