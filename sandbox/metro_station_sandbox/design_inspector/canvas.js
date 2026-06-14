import React from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
} from "@xyflow/react";

import { miniMapColor, nodeTypes } from "./flow_nodes.js?v=ops-config-1";
import { CanvasStatus } from "./status.js?v=ops-config-1";

const h = React.createElement;

export function Canvas({
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
  templateId,
}) {
  return h("main", { className: "canvas-shell" }, [
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
      nodesConnectable: true,
      elementsSelectable: true,
      selectNodesOnDrag: false,
      panOnDrag: [1, 2],
      nodeDragThreshold: 1,
      fitView: true,
      minZoom: 1.6,
      maxZoom: 10,
      defaultViewport: payload?.react_flow?.viewport || { x: 24, y: 24, zoom: 6 },
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
    h(CanvasStatus, { key: "canvas-status", compiling, error, loading, notice }),
  ]);
}
