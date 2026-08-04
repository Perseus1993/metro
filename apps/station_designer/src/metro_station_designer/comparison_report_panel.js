import React from "react";

import { ComparisonEvidenceTimeline } from "./comparison_evidence_timeline.js?v=control-plan-1";

const h = React.createElement;
const METRICS = [
  ["clearance_time_s", "清场时间 (s)"],
  ["peak_density_persons_m2", "峰值密度 (人/㎡)"],
  ["density_exposure_person_s", "密度暴露 (人·s)"],
  ["density_duration_above_threshold_s", "超阈持续时间 (s)"],
  ["max_gate_queue", "闸机排队"],
  ["max_vertical_queue", "垂直设施排队"],
  ["stuck_agents", "滞留人数"],
];
const ALGORITHM_METRICS = [
  ["routing_compute_duration_ms", "路由计算耗时 (ms)"],
  ["simulation_duration_ms", "仿真总耗时 (ms)"],
];

export const ComparisonReportPanel = ({ report, workflow }) => h(React.Fragment, null, [
  h(ReportSummary, { key: "summary", report }),
  h(ComparisonEvidenceTimeline, { key: "timeline", report }),
  h(DecisionEditor, { key: "decision", workflow }),
]);

const ReportSummary = ({ report }) => {
  const aggregate = report.aggregate || {};
  const baseline = aggregate.baseline?.metrics || {};
  const candidate = aggregate.candidate?.metrics || {};
  const deltas = aggregate.candidate_minus_baseline || {};
  const metrics = report.experiment_plan ? [...METRICS, ...ALGORITHM_METRICS] : METRICS;
  return h("div", { className: "experiment-report", "data-testid": "comparison-report" }, [
    h("strong", { key: "title" }, `结果 · ${report.status}`),
    h("small", { key: "run-status" }, runStatus(aggregate)),
    report.experiment_plan ? h(AlgorithmExecution, { key: "algorithms", aggregate }) : null,
    h("div", { key: "rows", className: "experiment-report__rows" }, metrics.map(([key, label]) =>
      h("div", { key, className: "experiment-report__row" }, [
        h("span", { key: "label" }, label),
        h("span", { key: "base" }, display(baseline[key]?.mean)),
        h("span", { key: "candidate" }, display(candidate[key]?.mean)),
        h("strong", { key: "delta" }, signed(deltas[key]?.mean_delta)),
        h("span", { key: "relative" }, percent(deltas[key]?.mean_relative_change)),
      ]),
    )),
    h("small", { key: "legend" }, "列：指标 / 基准 / 候选 / Δ / 相对变化"),
    report.methodology?.limitations?.length
      ? h("small", { key: "limitations", className: "experiment-boundary" },
          `限制：${report.methodology.limitations.join("；")}`,
        )
      : null,
  ]);
};

const AlgorithmExecution = ({ aggregate }) => h("div", {
  className: "experiment-algorithm-results",
  "data-testid": "algorithm-execution-summary",
}, ["baseline", "candidate"].map((role) => {
  const item = aggregate.algorithm_execution?.[role] || {};
  return h("div", { key: role }, [
    h("strong", { key: "identity" }, `${item.algorithm_id || "—"} · ${item.algorithm_version || "—"}`),
    h("span", { key: "rates" },
      ` 稳定 ${percent(item.stability_rate)} · 失败 ${percent(item.failure_rate)} · 决策日志 ${item.decision_log_count || 0}`,
    ),
  ]);
}));

const DecisionEditor = ({ workflow }) => {
  const update = (key, value) => workflow.setDecision({ ...workflow.decision, [key]: value });
  const evidence = workflow.job.report?.evidence?.baseline || {};
  return h("div", { className: "experiment-decision" }, [
    h("strong", { key: "title" }, "分析决策"),
    h("select", { key: "choice", value: workflow.decision.recommendation, onChange: (event) => update("recommendation", event.target.value) }, [
      h("option", { key: "adopt", value: "adopt" }, "采纳候选"),
      h("option", { key: "reject", value: "reject" }, "拒绝候选"),
      h("option", { key: "more", value: "more_evidence" }, "需要更多证据"),
    ]),
    h("textarea", { key: "reason", value: workflow.decision.rationale, onChange: (event) => update("rationale", event.target.value), placeholder: "填写判断依据" }),
    h("input", { key: "analyst", value: workflow.decision.analyst, onChange: (event) => update("analyst", event.target.value), placeholder: "分析人" }),
    h("p", { key: "boundary", className: "experiment-boundary" }, evidence.safe_use_boundary || "仅限内部探索。"),
    h("div", { key: "actions", className: "experiment-actions" }, [
      actionButton("save-decision", "记录决策", workflow.saveDecision, workflow.busy || !workflow.decision.rationale.trim()),
      actionButton("export-report", "导出报告 ZIP", workflow.exportReport, false),
    ]),
  ]);
};

const actionButton = (testId, label, onClick, disabled) => h("button", {
  key: testId, className: "button", "data-testid": testId, onClick, disabled,
}, label);

const runStatus = (aggregate) =>
  `基准 清场 ${aggregate.baseline?.cleared_runs || 0}/${aggregate.baseline?.runs || 0} · 右删失 ${aggregate.baseline?.right_censored_runs || 0}；候选 清场 ${aggregate.candidate?.cleared_runs || 0}/${aggregate.candidate?.runs || 0} · 右删失 ${aggregate.candidate?.right_censored_runs || 0}`;

const display = (value) => value === null || value === undefined ? "—" : Number(value).toFixed(2);
const signed = (value) => value === null || value === undefined
  ? "—"
  : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}`;
const percent = (value) => value === null || value === undefined
  ? "—"
  : `${(Number(value) * 100).toFixed(1)}%`;
