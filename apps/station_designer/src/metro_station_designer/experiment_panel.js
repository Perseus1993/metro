import React from "react";

import { ComparisonReportPanel } from "./comparison_report_panel.js?v=control-plan-1";
import { ControlPlanPanel } from "./control_plan_panel.js?v=control-plan-1";
import { AlgorithmExperimentPanel } from "./algorithm_experiment_panel.js?v=algorithm-experiment-1";

const h = React.createElement;

export function ExperimentPanel({ blocked, workflow }) {
  const report = workflow.job?.report;
  return h(React.Fragment, null, [
    h(ControlPlanPanel, {
      key: "control-plan",
      editor: workflow.controlPlan,
      locked: Boolean(workflow.baseline || workflow.busy),
    }),
    h("section", { key: "experiment", className: "section experiment-panel" }, [
    h("h2", { key: "title", className: "section__title" },
      workflow.comparisonMode === "algorithm" ? "6 疏散算法配对实验" : "6 方案 A/B 实验",
    ),
    h("p", { key: "intro", className: "experiment-panel__intro" },
      workflow.comparisonMode === "algorithm"
        ? "同一冻结案例、时间轴和 3 个种子分别运行两个路由算法。"
        : "冻结基准与随机种子，再把当前布局保存为候选方案。负 Δ 表示候选值更低。",
    ),
    h("div", { key: "templates", className: "experiment-actions" }, [
      h(ActionButton, {
        key: "algorithm-template",
        testId: "load-algorithm-template",
        label: "加载“疏散算法比较”模板",
        onClick: workflow.loadAlgorithmTemplate,
        disabled: workflow.busy,
      }),
      h(ImportPlanButton, { key: "import-plan", workflow }),
    ]),
    h(ControlGrid, { key: "controls", workflow }),
    h("div", { key: "baseline-actions", className: "experiment-actions" }, [
      h(ActionButton, {
        key: "save",
        testId: "save-baseline",
        label: workflow.baseline ? "重建基准" : "建立基准",
        onClick: workflow.saveBaseline,
        disabled: blocked || workflow.busy || !workflow.controlPlan.validation.valid,
      }),
      h(ImportButton, { key: "import", onFile: workflow.loadBaseline, disabled: workflow.busy }),
      h(ActionButton, {
        key: "export",
        testId: "export-baseline",
        label: "导出基准",
        onClick: workflow.exportBaseline,
        disabled: !workflow.baseline,
      }),
    ]),
    workflow.baseline ? h(CaseCard, { key: "baseline", label: "基准", value: workflow.baseline }) : null,
    h(AlgorithmExperimentPanel, { key: "algorithms", workflow }),
    h("div", { key: "candidate-actions", className: "experiment-actions" }, [
      workflow.comparisonMode === "case" ? h(ActionButton, {
        key: "candidate",
        testId: "save-candidate",
        label: workflow.candidate ? "更新候选" : "复制为候选",
        onClick: workflow.saveCandidate,
        disabled: blocked || workflow.busy || !workflow.baseline,
      }) : null,
      h(ActionButton, {
        key: "run",
        testId: "run-comparison",
        label: workflow.comparisonMode === "algorithm" ? "运行 2×3 配对实验" : "固定种子批量运行",
        primary: true,
        onClick: workflow.runComparison,
        disabled: workflow.comparisonMode === "algorithm"
          ? workflow.busy || !workflow.baseline || !workflow.algorithms.preflight.compatible
          : workflow.busy || !workflow.candidate || !workflow.differences.length,
      }),
    ]),
    workflow.comparisonMode === "case" && workflow.candidate
      ? h(CaseCard, { key: "candidate", label: "候选", value: workflow.candidate }) : null,
    workflow.comparisonMode === "case"
      ? h(DifferenceList, { key: "diff", differences: workflow.differences }) : null,
    workflow.job ? h(JobProgress, { key: "progress", job: workflow.job }) : null,
    report ? h(ComparisonReportPanel, { key: "report", report, workflow }) : null,
    workflow.error
      ? h("div", { key: "error", className: "simulation-result simulation-result--error" }, workflow.error)
      : null,
    ]),
  ]);
}

function ControlGrid({ workflow }) {
  const field = (key, label, type = "number", min = 1) => h("label", { key, className: "experiment-control" }, [
    h("span", { key: "label" }, label),
    h("input", {
      key: "input",
      type,
      min: type === "number" ? min : undefined,
      "data-testid": `experiment-${key}`,
      value: workflow.controls[key],
      disabled: Boolean(workflow.baseline),
      onChange: (event) => workflow.setControls({ ...workflow.controls, [key]: event.target.value }),
    }),
  ]);
  const fields = [
    field("seeds", "随机种子", "text"),
    field("demandMinutes", "需求窗口 min"),
    field("horizonMinutes", "清场窗口 min"),
    field("tickSeconds", "步长 s"),
  ];
  if (workflow.comparisonMode === "algorithm") {
    fields.push(field("initialPlatformPersons", "初始疏散人数"));
    fields.push(field("alarmDelaySeconds", "告警延迟 s", "number", 0));
  }
  return h("div", { className: "experiment-controls" }, fields);
}

function ImportButton({ onFile, disabled }) {
  return h("label", { className: `button${disabled ? " button--disabled" : ""}` }, [
    "导入基准",
    h("input", {
      key: "input",
      type: "file",
      accept: ".json,application/json",
      hidden: true,
      disabled,
      "data-testid": "import-baseline",
      onChange: (event) => event.target.files?.[0] && onFile(event.target.files[0]),
    }),
  ]);
}

function ImportPlanButton({ workflow }) {
  return h("label", { className: `button${workflow.busy ? " button--disabled" : ""}` }, [
    "导入实验计划",
    h("input", {
      key: "input",
      type: "file",
      accept: ".json,application/json",
      hidden: true,
      disabled: workflow.busy,
      "data-testid": "import-experiment-plan",
      onChange: (event) => event.target.files?.[0] && workflow.loadExperimentPlan(event.target.files[0]),
    }),
  ]);
}

function ActionButton({ testId, label, onClick, disabled, primary = false }) {
  return h("button", {
    className: `button${primary ? " button--primary" : ""}`,
    "data-testid": testId,
    onClick,
    disabled,
  }, label);
}

function CaseCard({ label, value }) {
  return h("div", { className: "experiment-case" }, [
    h("strong", { key: "name" }, `${label} · ${value.name}`),
    h("code", { key: "fingerprint" }, String(value.semantic_fingerprint || "").slice(0, 12)),
    h(
      "span",
      { key: "evidence", className: "experiment-case__evidence" },
      `${value.evidence?.calibration_status || "unknown"} · ${value.evidence?.model_version || "unknown model"} · seeds ${(value.seeds || []).join(", ")}`,
    ),
    h(
      "small",
      { key: "boundary", className: "experiment-case__boundary" },
      value.evidence?.safe_use_boundary || "未记录安全使用边界。",
    ),
  ]);
}

function DifferenceList({ differences }) {
  if (!differences.length) return null;
  return h("div", { className: "experiment-differences", "data-testid": "case-differences" }, [
    h("strong", { key: "title" }, `输入差异 ${differences.length} 项`),
    ...differences.slice(0, 6).map((item) => h("div", { key: item.path }, `${item.kind} · ${item.path}`)),
  ]);
}

function JobProgress({ job }) {
  const progress = job.progress || {};
  const percent = Math.round(Number(progress.fraction || 0) * 100);
  return h("div", { className: "experiment-job", "data-testid": "comparison-progress" }, [
    h("span", { key: "status" }, `${job.status} · ${percent}%`),
    h("progress", { key: "bar", max: 100, value: percent }),
    job.error ? h("span", { key: "error" }, job.error) : null,
  ]);
}
