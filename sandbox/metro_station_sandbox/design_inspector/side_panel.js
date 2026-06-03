import React from "react";

import { beginComponentDrag } from "./component_palette.js";

const h = React.createElement;

export function LeftPanel({ catalog, templateId, setTemplateId }) {
  return h("aside", { className: "side" }, [
    h("section", { key: "palette", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Components"),
      h(
        "div",
        { key: "grid", className: "palette-grid" },
        (catalog?.component_palette || []).map((component) =>
          h(
            "button",
            {
              key: component.id,
              className: `palette-item palette-item--${component.kind}`,
              draggable: true,
              onDragStart: (event) => beginComponentDrag(event, component),
            },
            [
              h("span", { key: "icon", className: "palette-item__icon" }, componentCode(component)),
              h("span", { key: "label", className: "palette-item__label" }, component.label),
            ],
          ),
        ),
      ),
    ]),
    h("section", { key: "templates", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Templates"),
      ...(catalog?.templates || []).map((template) =>
        h(
          "button",
          {
            key: template.id,
            className:
              template.id === templateId
                ? "template-card template-card--active"
                : "template-card",
            onClick: () => setTemplateId(template.id),
          },
          [
            h("div", { key: "label", className: "template-card__label" }, template.label),
            h("div", { key: "desc", className: "template-card__desc" }, template.description),
          ],
        ),
      ),
    ]),
    h("section", { key: "refs", className: "section" }, [
      h("h2", { key: "title", className: "section__title" }, "Reference Wheels"),
      ...(catalog?.reference_wheels || []).map((wheel) =>
        h("div", { key: wheel.name, className: "reference-row" }, [
          h("div", { key: "name", className: "reference-row__name" }, wheel.name),
          h("div", { key: "repo", className: "reference-row__repo" }, wheel.repo),
          h(
            "div",
            { key: "meta", className: "reference-row__meta" },
            wheel.absorbed?.length ? wheel.absorbed.join(", ") : `deferred: ${wheel.deferred}`,
          ),
        ]),
      ),
    ]),
  ]);
}

function componentCode(component) {
  if (component.kind === "entrance") {
    return "EN";
  }
  if (component.kind === "gate") {
    return "G";
  }
  if (component.kind === "platform_edge") {
    return "P";
  }
  if (component.kind === "shop") {
    return "S";
  }
  if (component.kind === "obstacle") {
    return "O";
  }
  return "EQ";
}
