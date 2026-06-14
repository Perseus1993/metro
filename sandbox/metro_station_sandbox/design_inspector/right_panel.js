import React from "react";

import { OperationsPanel } from "./operations_panel.js?v=ops-config-1";

const h = React.createElement;

export function RightPanel({
  clearEdges,
  onOperationChange,
  operationSchema,
  operations,
  payload,
  selectedEdge,
  selectedNode,
}) {
  const summary = payload?.summary || {};
  const issues = [
    ...(payload?.validation_issues || []),
    ...(payload?.graph?.diagnostics || []),
  ];
  return h("aside", { className: "inspector" }, [
    h(OperationsPanel, {
      key: "operations",
      onOperationChange,
      operations,
      schema: operationSchema,
    }),
    h("section", { key: "metrics", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Compile State"),
      h("div", { key: "grid", className: "metric-grid" }, [
        h(Metric, { key: "nodes", value: payload?.graph?.node_count || 0, label: "graph nodes" }),
        h(Metric, { key: "edges", value: payload?.graph?.edge_count || 0, label: "graph edges" }),
        h(Metric, { key: "connections", value: summary.document_connections || 0, label: "connections" }),
        h(Metric, { key: "fallback", value: summary.fallback_edges || 0, label: "fallback" }),
      ]),
    ]),
    h("section", { key: "selection", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Selection"),
      h(SelectionDetails, { key: "details", selectedEdge, selectedNode }),
    ]),
    h("section", { key: "origins", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Edge Origins"),
      h(OriginList, { key: "origin-list", graph: payload?.graph }),
      h(
        "button",
        { key: "clear", className: "button button--danger", onClick: clearEdges },
        "Clear edges",
      ),
    ]),
    h("section", { key: "diag", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Diagnostics"),
      h(DiagnosticList, { key: "diagnostics", issues }),
    ]),
  ]);
}

function Metric({ value, label }) {
  return h("div", { className: "metric-row" }, [
    h("span", { key: "value", className: "metric-row__value" }, String(value)),
    h("span", { key: "label", className: "metric-row__label" }, label),
  ]);
}

function SelectionDetails({ selectedEdge, selectedNode }) {
  if (selectedEdge) {
    const data = selectedEdge.data || {};
    return h("div", null, [
      h(DetailRow, { key: "id", label: "edge", value: selectedEdge.id }),
      h(DetailRow, {
        key: "endpoints",
        label: "ports",
        value: `${selectedEdge.source}.${selectedEdge.sourceHandle || "-"} -> ${selectedEdge.target}.${selectedEdge.targetHandle || "-"}`,
      }),
      h(DetailRow, { key: "kind", label: "kind", value: data.kind || "walk" }),
      h(DetailRow, {
        key: "status",
        label: "compile status",
        value: data.inspectorStatus || "pending",
      }),
    ]);
  }

  if (!selectedNode) {
    return h("div", { className: "empty" }, "No selection");
  }

  const data = selectedNode.data || {};
  const ports = data.ports || [];
  return h("div", null, [
    h(DetailRow, { key: "id", label: "node", value: selectedNode.id }),
    h(DetailRow, { key: "kind", label: "kind", value: data.kind || selectedNode.type }),
    h(DetailRow, { key: "role", label: "role", value: data.role || "-" }),
    h(DetailRow, {
      key: "movable",
      label: "movable",
      value: selectedNode.draggable === false ? "false" : "true",
    }),
    ports.length
      ? h(
          "div",
          { key: "ports", className: "port-list" },
          ports.map((port) => h(PortRow, { key: port.id, port })),
        )
      : h("div", { key: "empty", className: "empty" }, "No ports"),
  ]);
}

function DetailRow({ label, value }) {
  return h("div", { className: "detail-row" }, [
    h("div", { key: "label", className: "detail-row__label" }, label),
    h("div", { key: "value", className: "detail-row__value" }, String(value)),
  ]);
}

function PortRow({ port }) {
  return h("div", { className: "port-row" }, [
    h("div", { key: "main" }, [
      h("div", { key: "id", className: "port-row__id" }, port.id),
      h("div", { key: "meta", className: "port-row__meta" }, `${port.kind} / ${port.direction}`),
    ]),
    h("span", { key: "level", className: "pill" }, port.level_id || "-"),
  ]);
}

function OriginList({ graph }) {
  const entries = Object.entries(graph?.origin_counts || {});
  if (!entries.length) {
    return h("div", { className: "empty" }, "No compiled graph edges");
  }
  return h(
    "div",
    { className: "origin-list" },
    entries.map(([origin, count]) =>
      h("div", { key: origin, className: "origin-row" }, [
        h("div", { key: "name", className: "origin-row__name" }, origin),
        h("div", { key: "meta", className: "origin-row__meta" }, `${count} graph edges`),
      ]),
    ),
  );
}

function DiagnosticList({ issues }) {
  if (!issues.length) {
    return h("div", { className: "empty" }, "No diagnostics");
  }
  return h(
    "div",
    { className: "diagnostic-list" },
    issues.map((issue, index) =>
      h(
        "div",
        {
          key: `${issue.code}:${index}`,
          className: `diagnostic-row diagnostic-row--${issue.severity || "info"}`,
        },
        [
          h("div", { key: "code", className: "diagnostic-row__code" }, issue.code),
          h("div", { key: "msg", className: "diagnostic-row__message" }, issue.message),
        ],
      ),
    ),
  );
}
