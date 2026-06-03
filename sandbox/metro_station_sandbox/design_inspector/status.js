import React from "react";

const h = React.createElement;

export function StatusStrip({ payload }) {
  const summary = payload?.summary || {};
  const status = summary.status || "warning";
  return h("div", { className: "status-strip" }, [
    h("span", { key: "status", className: `pill pill--${status}` }, status.toUpperCase()),
    h(
      "span",
      { key: "errors", className: pillClass(summary.validation_errors) },
      `validation errors ${summary.validation_errors || 0}`,
    ),
    h(
      "span",
      { key: "fallback", className: pillClass(summary.fallback_edges) },
      `fallback edges ${summary.fallback_edges || 0}`,
    ),
    h(
      "span",
      { key: "inferred", className: pillClass(summary.inferred_endpoints) },
      `inferred endpoints ${summary.inferred_endpoints || 0}`,
    ),
  ]);
}

export function CanvasStatus({ compiling, error, loading }) {
  const pills = [];
  if (loading) {
    pills.push(h("span", { key: "loading", className: "pill" }, "loading"));
  }
  if (compiling) {
    pills.push(h("span", { key: "compiling", className: "pill" }, "compiling"));
  }
  if (error) {
    pills.push(h("span", { key: "error", className: "pill pill--error" }, error));
  }
  return h("div", { className: "canvas-status" }, pills);
}

function pillClass(value) {
  return value ? "pill pill--warning" : "pill pill--ok";
}
