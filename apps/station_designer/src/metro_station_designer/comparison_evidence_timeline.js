import React, { useState } from "react";

const h = React.createElement;

export const ComparisonEvidenceTimeline = ({ report }) => {
  const [selectedKey, setSelectedKey] = useState("");
  const entries = evidenceEntries(report);
  if (!entries.length) return null;
  const horizonSeconds = Number(report.spec?.baseline?.simulation?.horizon_minutes || 1) * 60;
  const selected = entries.find((entry) => entry.key === selectedKey) || null;
  return h("div", { className: "report-evidence", "data-testid": "report-evidence-timeline" }, [
    h("strong", { key: "title" }, "事件与瓶颈回放"),
    h("div", { key: "axis", className: "report-evidence__axis" }, [
      h("span", { key: "start" }, "0s"),
      h("span", { key: "end" }, `${horizonSeconds}s`),
    ]),
    h("div", { key: "track", className: "report-evidence__track" }, entries.map((entry) =>
      h("button", {
        key: entry.key,
        className: `report-evidence__marker report-evidence__marker--${entry.kind}`,
        style: { left: `${Math.min(100, entry.timeSeconds / horizonSeconds * 100)}%` },
        title: `${entry.label} · ${entry.timeSeconds}s`,
        "data-testid": "report-evidence-marker",
        onClick: () => setSelectedKey(entry.key),
      }),
    )),
    h("div", { key: "list", className: "report-evidence__list" }, entries.map((entry) =>
      h("button", {
        key: entry.key,
        className: `report-evidence__jump${selectedKey === entry.key ? " report-evidence__jump--selected" : ""}`,
        "data-testid": `report-jump-${entry.kind}`,
        onClick: () => setSelectedKey(entry.key),
      }, [
        h("span", { key: "time" }, `${entry.timeSeconds}s`),
        h("strong", { key: "label" }, entry.label),
        h("span", { key: "run" }, `${entry.role} · seed ${entry.seed}`),
      ]),
    )),
    selected ? h(EvidenceDetail, { key: "detail", entry: selected }) : null,
  ]);
};

const EvidenceDetail = ({ entry }) => h(
  "div",
  { className: "report-evidence__detail", "data-testid": "report-replay-position" },
  [
    h("strong", { key: "title" }, `已定位 ${entry.timeSeconds}s · ${entry.label}`),
    h("span", { key: "where" }, entry.location || "位置未记录"),
    entry.status ? h("span", { key: "status" }, ` · ${entry.status}`) : null,
    entry.offset === null
      ? null
      : h("span", { key: "offset" }, ` · 应用偏差 ${signed(entry.offset)}s`),
  ],
);

const evidenceEntries = (report) => {
  const entries = [];
  for (const run of report.runs || []) {
    for (const event of run.control_events || []) entries.push(controlEntry(report, run, event));
    if (run.top_bottleneck) entries.push(bottleneckEntry(run));
  }
  return entries.sort((left, right) => left.timeSeconds - right.timeSeconds || left.key.localeCompare(right.key));
};

const controlEntry = (report, run, event) => {
  const measure = controlMeasure(report, run.role, event.measure_id);
  const applied = Number(event.applied_seconds || 0);
  const scheduled = Number(event.scheduled_seconds || 0);
  return {
    key: `${run.role}-${run.seed}-${event.event_id}-${event.status}`,
    kind: "control",
    timeSeconds: applied,
    label: `${measure?.label || event.measure_id} · ${event.action}`,
    role: run.role,
    seed: run.seed,
    status: event.status,
    offset: applied - scheduled,
    location: controlLocation(measure, event),
  };
};

const bottleneckEntry = (run) => {
  const item = run.top_bottleneck;
  return {
    key: `${run.role}-${run.seed}-bottleneck`,
    kind: "bottleneck",
    timeSeconds: Number(item.time_seconds || 0),
    label: `瓶颈 · ${item.label || item.facility_id || "unknown"}`,
    role: run.role,
    seed: run.seed,
    status: `压力 ${Number(item.pressure || 0).toFixed(2)}`,
    offset: null,
    location: item.facility_id || "位置未记录",
  };
};

const controlMeasure = (report, role, measureId) => {
  const analysisCase = report.spec?.[role] || {};
  return analysisCase.simulation?.control_plan?.measures?.find(
    (measure) => measure.measure_id === measureId,
  );
};

const controlLocation = (measure, event) => {
  if (!measure) return event.target_id || event.level_id || "位置未记录";
  const geometry = measure.parameters?.geometry;
  if (!geometry) return measure.target_id || measure.level_id || "位置未记录";
  const x = Number(geometry.x_m || 0) + Number(geometry.width_m || 0) / 2;
  const y = Number(geometry.y_m || 0) + Number(geometry.height_m || 0) / 2;
  return `${measure.level_id || "-"} · (${x.toFixed(1)}, ${y.toFixed(1)})`;
};

const signed = (value) => `${value > 0 ? "+" : ""}${Number(value).toFixed(1)}`;
