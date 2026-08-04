import React from "react";

import { StatusStrip } from "./status.js?v=ops-config-1";

const h = React.createElement;

export function TopBar({
  catalog,
  compiling,
  loading,
  onCompile,
  onGenerate,
  onNewStation,
  onDeleteSelectedEdge,
  payload,
  selectedEdge,
}) {
  return h("header", { className: "topbar" }, [
    h("div", { key: "brand", className: "brand" }, [
      h("h1", { key: "title", className: "brand__title" }, "地铁站搭建与仿真"),
      h("span", { key: "meta", className: "brand__meta" }, payload?.document?.label || ""),
    ]),
    h("div", { key: "toolbar", className: "toolbar" }, [
      h("button", {
        key: "new-station",
        className: "button button--new-station",
        disabled: loading || !catalog,
        onClick: onNewStation,
        "data-testid": "new-station",
      }, "新建 / 重新配置站点"),
      h(
        "button",
        {
          key: "compile",
          className: "button",
          disabled: loading || compiling,
          onClick: onCompile,
        },
        compiling ? "校验中" : "重新校验",
      ),
      h(
        "button",
        {
          key: "generate",
          "data-testid": "generate-station",
          className: "button button--primary",
          disabled: loading || compiling,
          onClick: onGenerate,
        },
        compiling ? "生成中" : "2 生成站点",
      ),
      h(
        "button",
        {
          key: "delete",
          className: "button button--danger",
          disabled: !selectedEdge,
          onClick: onDeleteSelectedEdge,
        },
        "删除连接",
      ),
    ]),
    h(StatusStrip, { key: "status", payload }),
  ]);
}
