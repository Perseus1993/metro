import React from "react";

import { OperationsPanel } from "./operations_panel.js?v=ops-config-1";

const h = React.createElement;

export function RightPanel({
  clearEdges,
  compiling,
  onOperationChange,
  operationSchema,
  operations,
  payload,
  runSimulation,
  selectedEdge,
  selectedNode,
  simProgress,
  simResult,
  simulating,
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
    h("section", { key: "simulation", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Simulation"),
      h(
        "button",
        {
          key: "run",
          className: "button button--primary",
          onClick: runSimulation,
          disabled: simulating || compiling,
        },
        simulating ? "Simulating..." : "Simulate",
      ),
      simProgress ? h(SimulationProgress, { key: "progress", progress: simProgress }) : null,
      simResult ? h(SimulationResult, { key: "result", result: simResult }) : null,
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

function SimulationProgress({ progress }) {
  const numericProgress = Number(progress.progress || 0);
  const percentValue = Number.isFinite(numericProgress)
    ? Math.max(0, Math.min(100, numericProgress * 100))
    : 0;
  const total = Number(progress.total_steps || 0);
  const step = Number(progress.step || 0);
  const label = total > 0 ? `${step}/${total}` : progress.status || "queued";
  return h("div", { className: "simulation-progress" }, [
    h("div", { key: "meta", className: "simulation-progress__meta" }, [
      h("span", { key: "status" }, progress.status || "queued"),
      h("span", { key: "steps" }, label),
    ]),
    h("div", { key: "track", className: "simulation-progress__track" }, [
      h("div", {
        key: "bar",
        className: "simulation-progress__bar",
        style: { width: `${percentValue.toFixed(1)}%` },
      }),
    ]),
  ]);
}

function SimulationResult({ result }) {
  if (result.status === "error") {
    return h("div", { className: "simulation-result simulation-result--error" }, [
      h("span", { key: "status", className: "pill pill--error" }, "error"),
      h("div", { key: "message", className: "simulation-result__message" }, result.error || "Simulation failed"),
    ]);
  }

  const report = result.trajectory_report || {};
  const metrics = result.metrics || {};
  const passFail = report.pass_fail || "n/a";
  const pillClass =
    passFail === "pass"
      ? "pill pill--ok"
      : passFail === "warn"
        ? "pill pill--warning"
        : "pill pill--error";
  return h("div", { className: "simulation-result" }, [
    h("span", { key: "status", className: pillClass }, passFail),
    h("div", { key: "grid", className: "metric-grid metric-grid--compact" }, [
      h(Metric, {
        key: "completion",
        value: percent(report.completion_rate),
        label: "completion",
      }),
      h(Metric, {
        key: "remaining",
        value: metrics.remaining_agents ?? metrics.station_persons ?? 0,
        label: "remaining",
      }),
      h(Metric, {
        key: "stuck",
        value: report.stuck_agents ?? 0,
        label: "stuck",
      }),
      h(Metric, {
        key: "vertical",
        value: metrics.vertical_queue_persons ?? 0,
        label: "vertical q",
      }),
    ]),
    h(IssueList, { key: "issues", issues: report.issues || [] }),
  ]);
}

function IssueList({ issues }) {
  if (!issues.length) {
    return h("div", { className: "empty" }, "No trajectory issues");
  }
  return h(
    "div",
    { className: "simulation-issues" },
    issues.map((issue, index) =>
      h("div", { key: index, className: "simulation-issue" }, String(issue)),
    ),
  );
}

function percent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "n/a";
  }
  return `${(numeric * 100).toFixed(1)}%`;
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
