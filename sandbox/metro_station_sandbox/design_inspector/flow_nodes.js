import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";

const h = React.createElement;

export const nodeTypes = {
  levelGroup: memo(LevelGroupNode),
  floorZone: memo(StationElementNode),
  facilityNode: memo(StationElementNode),
  verticalConnector: memo(StationElementNode),
  queueLane: memo(QueueNode),
  queueGrid: memo(QueueNode),
};

export function miniMapColor(node) {
  if (node.type === "levelGroup") {
    return "#ded7cd";
  }
  if (node.type === "verticalConnector") {
    return "#8c73aa";
  }
  if (node.data?.kind === "gate") {
    return "#26806f";
  }
  if (node.data?.kind === "platform_edge") {
    return "#2a5f91";
  }
  if (node.data?.kind === "entrance") {
    return "#b46c1e";
  }
  return "#fbfaf7";
}

function LevelGroupNode({ data }) {
  return h("div", { className: "level-node" }, [
    h("div", { key: "label", className: "level-node__label" }, data.label),
  ]);
}

function StationElementNode({ id, type, data }) {
  const ports = data.ports || [];
  const className = [
    "station-node",
    `station-node--${type}`,
    `station-node--${data.kind}`,
  ].join(" ");
  const code = elementCode(type, data);
  return h("div", { className }, [
    h("div", { key: "drag-pad", className: "station-node__drag-pad" }),
    code
      ? h("div", { key: "code", className: "station-node__code" }, code)
      : null,
    ...ports.flatMap((port, index) => renderPortHandles(data, port, index, ports.length)),
  ]);
}

function QueueNode({ id, data }) {
  return h("div", { className: "queue-node", title: data.label || data.queue_id || id });
}

function elementCode(type, data) {
  if (type === "floorZone") {
    return "";
  }
  if (data.kind === "entrance") {
    return "EN";
  }
  if (data.kind === "gate") {
    return "G";
  }
  if (data.role === "vertical_connector") {
    return "V";
  }
  if (data.kind === "platform_edge") {
    return "P";
  }
  if (data.kind === "equipment") {
    return "EQ";
  }
  if (data.kind === "shop") {
    return "S";
  }
  return "";
}

function renderPortHandles(data, port, index, total) {
  const placement = portPlacement(data.geometry, port, index, total);
  const handleTypes =
    port.direction === "in"
      ? ["target"]
      : port.direction === "out"
        ? ["source"]
        : ["source", "target"];
  return handleTypes.map((handleType) =>
    h(Handle, {
      key: `${port.id}:${handleType}`,
      id: port.id,
      type: handleType,
      position: placement.position,
      className: [
        "station-handle",
        `station-handle--${port.kind}`,
        `station-handle--${handleType}`,
      ].join(" "),
      style: placement.style,
      title: `${port.id} ${port.kind} ${port.direction}`,
    }),
  );
}

function portPlacement(geometry, port, index, total) {
  if (geometry && Array.isArray(port.position_m) && geometry.width_m && geometry.height_m) {
    const xPct = clamp(((port.position_m[0] - geometry.x_m) / geometry.width_m) * 100, 8, 92);
    const yPct = clamp(((port.position_m[1] - geometry.y_m) / geometry.height_m) * 100, 8, 92);
    const distances = [
      ["left", xPct],
      ["right", 100 - xPct],
      ["top", yPct],
      ["bottom", 100 - yPct],
    ];
    const side = distances.sort((a, b) => a[1] - b[1])[0][0];
    return sidePlacement(side, xPct, yPct);
  }

  const offset = Math.round(((index + 1) / (total + 1)) * 100);
  if (port.direction === "in") {
    return sidePlacement("left", 0, offset);
  }
  if (port.direction === "out") {
    return sidePlacement("right", 100, offset);
  }
  return sidePlacement(index % 2 === 0 ? "top" : "bottom", offset, 0);
}

function sidePlacement(side, xPct, yPct) {
  if (side === "left") {
    return { position: Position.Left, style: { top: `${yPct}%` } };
  }
  if (side === "right") {
    return { position: Position.Right, style: { top: `${yPct}%` } };
  }
  if (side === "bottom") {
    return { position: Position.Bottom, style: { left: `${xPct}%` } };
  }
  return { position: Position.Top, style: { left: `${xPct}%` } };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
