import React from "react";

const h = React.createElement;

export function StatusStrip({ payload }) {
  const summary = payload?.summary || {};
  const status = summary.status || "warning";
  return h("div", { className: "status-strip" }, [
    h("span", { key: "status", className: `pill pill--${status}` }, statusLabel(status)),
    h(
      "span",
      { key: "errors", className: pillClass(summary.validation_errors) },
      `布局错误 ${summary.validation_errors || 0}`,
    ),
    h(
      "span",
      { key: "fallback", className: pillClass(summary.fallback_edges) },
      `自动补边 ${summary.fallback_edges || 0}`,
    ),
    h(
      "span",
      { key: "inferred", className: pillClass(summary.inferred_endpoints) },
      `推断端口 ${summary.inferred_endpoints || 0}`,
    ),
  ]);
}

export function CanvasStatus({ compiling, error, loading, notice }) {
  const pills = [];
  if (loading) {
    pills.push(h("span", { key: "loading", className: "pill" }, "加载中"));
  }
  if (compiling) {
    pills.push(h("span", { key: "compiling", className: "pill" }, "校验中"));
  }
  if (error) {
    pills.push(h("span", { key: "error", className: "pill pill--error" }, error));
  }
  if (!error && notice) {
    pills.push(h("span", { key: "notice", className: "pill pill--ok" }, notice));
  }
  return h("div", { className: "canvas-status" }, pills);
}

function pillClass(value) {
  return value ? "pill pill--warning" : "pill pill--ok";
}

function statusLabel(status) {
  return { ok: "可运行", warning: "需注意", error: "需修复" }[status] || status;
}
