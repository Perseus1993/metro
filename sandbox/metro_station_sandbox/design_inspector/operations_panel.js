import React from "react";

const h = React.createElement;

export function OperationsPanel({ onOperationChange, operations, schema }) {
  if (!schema?.length) {
    return null;
  }
  return h("section", { className: "section" }, [
    h("h2", { key: "title", className: "section__title" }, "Operations"),
    h(
      "div",
      { key: "groups", className: "operation-groups" },
      schema.map((group) =>
        h("div", { key: group.id, className: "operation-group" }, [
          h("div", { key: "label", className: "operation-group__label" }, group.label),
          h(
            "div",
            { key: "fields", className: "operation-fields" },
            (group.fields || []).map((field) =>
              h(OperationField, {
                key: field.id,
                field,
                onOperationChange,
                value: operations?.[field.id],
              }),
            ),
          ),
        ]),
      ),
    ),
  ]);
}

function OperationField({ field, onOperationChange, value }) {
  return h("label", { className: "operation-field" }, [
    h("span", { key: "label", className: "operation-field__label" }, field.label),
    h("span", { key: "control", className: "operation-field__control" }, [
      h("input", {
        key: "input",
        className: "operation-field__input",
        type: "number",
        inputMode: field.kind === "integer" ? "numeric" : "decimal",
        min: field.min,
        max: field.max,
        step: field.step,
        value: value ?? field.default ?? "",
        onChange: (event) => onOperationChange(field.id, event.target.value),
      }),
      h("span", { key: "unit", className: "operation-field__unit" }, field.unit),
    ]),
  ]);
}
