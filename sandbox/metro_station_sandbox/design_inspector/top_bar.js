import React from "react";

import { StatusStrip } from "./status.js?v=ops-config-1";

const h = React.createElement;

export function TopBar({
  catalog,
  compiling,
  loading,
  onCompile,
  onDeleteSelectedEdge,
  onReset,
  payload,
  selectedEdge,
  setTemplateId,
  templateId,
}) {
  return h("header", { className: "topbar" }, [
    h("div", { key: "brand", className: "brand" }, [
      h("h1", { key: "title", className: "brand__title" }, "Metro Station Design Inspector"),
      h("span", { key: "meta", className: "brand__meta" }, payload?.document?.label || ""),
    ]),
    h("div", { key: "toolbar", className: "toolbar" }, [
      h(
        "select",
        {
          key: "select",
          className: "template-select",
          value: templateId,
          onChange: (event) => setTemplateId(event.target.value),
        },
        (catalog?.templates || []).map((template) =>
          h("option", { key: template.id, value: template.id }, template.label),
        ),
      ),
      h(
        "button",
        {
          key: "compile",
          className: "button",
          disabled: loading || compiling,
          onClick: onCompile,
        },
        compiling ? "Compiling" : "Compile",
      ),
      h(
        "button",
        { key: "reset", className: "button", disabled: loading, onClick: onReset },
        "Reset",
      ),
      h(
        "button",
        {
          key: "delete",
          className: "button button--danger",
          disabled: !selectedEdge,
          onClick: onDeleteSelectedEdge,
        },
        "Delete edge",
      ),
    ]),
    h(StatusStrip, { key: "status", payload }),
  ]);
}
