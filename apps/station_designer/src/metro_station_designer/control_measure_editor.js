import React from "react";

const h = React.createElement;

export const ControlMeasureEditor = ({ definition, editor, locked, measure }) => {
  const events = editor.plan.events
    .filter((event) => event.measure_id === measure.measure_id)
    .sort((left, right) => eventOrder(left, definition) - eventOrder(right, definition));
  const targets = targetOptions(definition, editor.catalog);
  return h("article", {
    className: "control-measure",
    "data-testid": `control-measure-${measure.kind}`,
  }, [
    h("header", { key: "head", className: "control-measure__head" }, [
      h("span", { key: "kind", className: "control-kind" }, definition.label),
      h("span", { key: "status", className: `control-status control-status--${definition.runtime_status}` },
        definition.runtime_status === "available" ? "可运行" : "合同已冻结",
      ),
      h("button", {
        key: "remove",
        className: "button button--danger control-measure__remove",
        disabled: locked,
        "data-testid": `control-remove-${measure.kind}`,
        onClick: () => editor.removeMeasure(measure.measure_id),
      }, "删除"),
    ]),
    h(TextField, {
      key: "label",
      label: "名称",
      value: measure.label,
      disabled: locked,
      onChange: (value) => editor.reviseMeasure(measure.measure_id, { label: value }),
    }),
    definition.placement === "geometry"
      ? h(GeometryFields, { key: "geometry", editor, locked, measure })
      : null,
    definition.placement === "level"
      ? h(SelectField, {
        key: "level",
        label: "作用楼层",
        value: measure.level_id || "",
        options: (editor.catalog?.levels || []).map((level) => [level.id, level.label]),
        disabled: locked,
        onChange: (value) => editor.reviseMeasure(measure.measure_id, { level_id: value || null }),
      })
      : null,
    ["facility", "escalator"].includes(definition.placement)
      ? h(SelectField, {
        key: "target",
        label: "目标设施",
        value: measure.target_id || "",
        options: targets.map((target) => [target.id, `${target.label} · ${target.id}`]),
        disabled: locked,
        onChange: (value) => editor.reviseMeasure(measure.measure_id, { target_id: value || null }),
      })
      : null,
    h("div", { key: "events", className: "control-events" }, events.map((event, index) =>
      h(EventField, {
        key: event.event_id,
        definition,
        editor,
        event,
        index,
        locked,
        measure,
      }),
    )),
  ]);
};

const eventOrder = (event, definition) => {
  if (event.action === definition.start_action) return 0;
  if (event.action === definition.end_action) return 1;
  return 2;
};

const GeometryFields = ({ editor, locked, measure }) => {
  const geometry = measure.parameters?.geometry || {};
  const numberField = (key, label, min) => h(TextField, {
    key,
    label,
    type: "number",
    min,
    step: 0.5,
    value: geometry[key] ?? 0,
    disabled: locked,
    testId: `control-geometry-${key}`,
    onChange: (value) => editor.reviseGeometry(measure.measure_id, { [key]: Number(value) }),
  });
  return h("div", { className: "control-geometry" }, [
    h(SelectField, {
      key: "level",
      label: "楼层",
      value: measure.level_id || "",
      options: (editor.catalog?.levels || []).map((level) => [level.id, level.label]),
      disabled: locked,
      onChange: (value) => editor.reviseMeasure(measure.measure_id, { level_id: value || null }),
    }),
    numberField("x_m", "X (m)"),
    numberField("y_m", "Y (m)"),
    numberField("width_m", "宽 (m)", 0.5),
    numberField("height_m", "高 (m)", 0.5),
  ]);
};

const EventField = ({ definition, editor, event, index, locked, measure }) => h(
  "div",
  { className: "control-event" },
  [
    h("span", { key: "action" }, `${index === 0 ? "开始" : "结束"} · ${event.action}`),
    h("input", {
      key: "time",
      type: "number",
      min: 0,
      max: editor.horizonSeconds - editor.tickSeconds,
      step: editor.tickSeconds,
      value: event.at_seconds,
      disabled: locked,
      "aria-label": `${measure.label}${index === 0 ? "开始" : "结束"}时刻`,
      "data-testid": `control-${index === 0 ? "start" : "end"}-${measure.kind}`,
      onChange: (change) => editor.reviseEvent(event.event_id, {
        at_seconds: Number(change.target.value),
      }),
    }),
    h("span", { key: "unit" }, "s"),
    index === 0 && definition.directions?.length
      ? h("select", {
        key: "direction",
        value: event.parameters?.direction || definition.directions[0],
        disabled: locked,
        onChange: (change) => editor.reviseEvent(event.event_id, {
          parameters: { ...event.parameters, direction: change.target.value },
        }),
      }, definition.directions.map((direction) =>
        h("option", { key: direction, value: direction }, direction),
      ))
      : null,
  ],
);

const TextField = ({ disabled, label, min, onChange, step, testId, type = "text", value }) => h(
  "label",
  { className: "control-field" },
  [
    h("span", { key: "label" }, label),
    h("input", {
      key: "input", disabled, min, step, type, value,
      "data-testid": testId,
      onChange: (event) => onChange(event.target.value),
    }),
  ],
);

const SelectField = ({ disabled, label, onChange, options, value }) => h(
  "label",
  { className: "control-field" },
  [
    h("span", { key: "label" }, label),
    h("select", { key: "select", disabled, value, onChange: (event) => onChange(event.target.value) }, [
      h("option", { key: "empty", value: "" }, "请选择"),
      ...options.map(([optionValue, optionLabel]) =>
        h("option", { key: optionValue, value: optionValue }, optionLabel),
      ),
    ]),
  ],
);

const targetOptions = (definition, catalog) => (catalog?.facility_targets || []).filter(
  (target) => definition.placement !== "escalator" || target.kind === "escalator",
);
