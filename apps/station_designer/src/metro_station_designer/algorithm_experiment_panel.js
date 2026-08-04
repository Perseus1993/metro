import React from "react";

const h = React.createElement;

export const AlgorithmExperimentPanel = ({ workflow }) => {
  const algorithms = workflow.algorithms;
  if (workflow.comparisonMode !== "algorithm") return null;
  return h("div", { className: "experiment-algorithms", "data-testid": "algorithm-config" }, [
    h("strong", { key: "title" }, "疏散路由算法（唯一实验变量）"),
    h(AlgorithmField, { key: "baseline", role: "baseline", label: "内置基线", algorithms }),
    h(AlgorithmField, { key: "candidate", role: "candidate", label: "候选插件", algorithms }),
    h("div", { key: "preflight", className: "experiment-actions" }, [
      button("algorithm-preflight", "兼容性预检", workflow.preflightAlgorithms),
      h("span", {
        key: "status",
        "data-testid": "algorithm-preflight-status",
      }, algorithms.preflight.message),
    ]),
    h("details", { key: "register" }, [
      h("summary", { key: "summary" }, "注册本地已审查插件"),
      h("input", {
        key: "path",
        value: algorithms.manifestPath,
        placeholder: "manifest.json 的本地路径",
        "data-testid": "algorithm-manifest-path",
        onChange: (event) => algorithms.setManifestPath(event.target.value),
      }),
      button("algorithm-register", "运行 10 案例并注册", workflow.registerAlgorithm),
    ]),
    algorithms.error
      ? h("div", { key: "error", className: "simulation-result simulation-result--error" }, algorithms.error)
      : null,
    h("small", { key: "boundary" }, "独立进程用于故障隔离，不是不可信代码安全沙箱。"),
  ]);
};

const AlgorithmField = ({ role, label, algorithms }) => h("label", {
  className: "experiment-algorithm",
}, [
  h("span", { key: "label" }, label),
  h("select", {
    key: "select",
    value: algorithms.selections[role],
    "data-testid": `algorithm-${role}`,
    onChange: (event) => algorithms.updateSelection(role, event.target.value),
  }, algorithms.catalog.map((item) => h("option", {
    key: item.registration_id,
    value: item.registration_id,
  }, `${item.manifest.metadata?.label || item.manifest.plugin_id} · ${item.manifest.plugin_version}`))),
  h("textarea", {
    key: "parameters",
    value: algorithms.parameterText[role],
    "data-testid": `algorithm-${role}-parameters`,
    onChange: (event) => algorithms.updateParameters(role, event.target.value),
  }),
]);

const button = (testId, label, onClick) => h("button", {
  key: testId,
  className: "button",
  type: "button",
  "data-testid": testId,
  onClick,
}, label);
