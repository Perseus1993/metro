import React from "react";

import { ControlMeasureEditor } from "./control_measure_editor.js?v=control-plan-1";

const h = React.createElement;

export const ControlPlanPanel = ({ editor, locked }) => {
  const definitions = editor.catalog?.measure_types || [];
  const byKind = new Map(definitions.map((item) => [item.kind, item]));
  return h("section", { className: "section control-plan-panel", "data-testid": "control-plan-panel" }, [
    h("div", { key: "heading", className: "control-plan-heading" }, [
      h("h2", { key: "title", className: "section__title" }, "5 管控措施与时间轴"),
      locked ? h("span", { key: "lock", className: "control-plan-lock" }, "案例已冻结") : null,
    ]),
    h("p", { key: "intro", className: "control-plan-intro" },
      "设置开始与结束时刻；事件必须与仿真步长对齐。灰色组件已冻结合同，运行语义仍在研发。",
    ),
    h("div", { key: "library", className: "control-library" }, definitions.map((definition) => {
      const unavailable = definition.runtime_status !== "available";
      return h("button", {
        key: definition.kind,
        className: `control-library__item${unavailable ? " control-library__item--planned" : ""}`,
        disabled: locked || unavailable,
        title: unavailable ? "合同已冻结，运行接入中" : `添加${definition.label}`,
        "data-testid": `control-add-${definition.kind}`,
        onClick: () => editor.addMeasure(definition.kind),
      }, [
        h("strong", { key: "label" }, definition.label),
        h("small", { key: "status" }, unavailable ? "接入中" : "可运行"),
      ]);
    })),
    editor.plan.measures.length
      ? h(TimelineTrack, { key: "timeline", editor })
      : h("div", { key: "empty", className: "control-plan-empty" }, "尚未添加管控措施。"),
    h(IssueSummary, { key: "issues", validation: editor.validation }),
    h("div", { key: "measures", className: "control-measure-list" }, editor.plan.measures.map((measure) =>
      h(ControlMeasureEditor, {
        key: measure.measure_id,
        definition: byKind.get(measure.kind),
        editor,
        locked,
        measure,
      }),
    )),
  ]);
};

const TimelineTrack = ({ editor }) => {
  const events = [...editor.plan.events].sort((left, right) => left.at_seconds - right.at_seconds);
  return h("div", { className: "control-timeline", "data-testid": "control-timeline" }, [
    h("div", { key: "axis", className: "control-timeline__axis" }, [
      h("span", { key: "start" }, "0s"),
      h("span", { key: "end" }, `${editor.horizonSeconds}s`),
    ]),
    h("div", { key: "track", className: "control-timeline__track" }, events.map((event) => {
      const measure = editor.plan.measures.find((item) => item.measure_id === event.measure_id);
      const left = Math.min(100, Number(event.at_seconds) / editor.horizonSeconds * 100);
      return h("button", {
        key: event.event_id,
        className: "control-timeline__marker",
        style: { left: `${left}%` },
        title: `${measure?.label || event.measure_id} · ${event.action} · ${event.at_seconds}s`,
        "data-testid": "control-timeline-marker",
      }, String(event.at_seconds));
    })),
  ]);
};

const IssueSummary = ({ validation }) => {
  if (!validation.errors.length && !validation.warnings.length) {
    return h("div", { className: "control-plan-valid", "data-testid": "control-plan-valid" },
      "时间轴校验通过",
    );
  }
  return h("div", { className: "control-plan-issues", "data-testid": "control-plan-issues" }, [
    ...validation.errors.map((message, index) =>
      h("div", { key: `error-${index}`, className: "control-plan-issue control-plan-issue--error" }, message),
    ),
    ...validation.warnings.map((message, index) =>
      h("div", { key: `warning-${index}`, className: "control-plan-issue control-plan-issue--warning" }, message),
    ),
  ]);
};
