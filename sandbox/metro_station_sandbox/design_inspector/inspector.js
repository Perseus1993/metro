import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";

import { Canvas } from "./canvas.js";
import { useStationInspectorState } from "./inspector_state.js";
import { RightPanel } from "./right_panel.js";
import { LeftPanel } from "./side_panel.js";
import { TopBar } from "./top_bar.js";

const h = React.createElement;
const DEFAULT_TEMPLATE_ID = "visual_demo_station";

function App() {
  return h(ReactFlowProvider, null, h(StationDesignInspector));
}

function StationDesignInspector() {
  const state = useStationInspectorState(DEFAULT_TEMPLATE_ID);

  return h("div", { className: "app" }, [
    h(TopBar, {
      key: "topbar",
      catalog: state.catalog,
      compiling: state.compiling,
      loading: state.loading,
      payload: state.payload,
      templateId: state.templateId,
      onCompile: state.compileDraft,
      onDeleteSelectedEdge: state.deleteSelectedEdge,
      onReset: state.resetTemplate,
      selectedEdge: state.selectedEdge,
      setTemplateId: state.setTemplateId,
    }),
    h("div", { key: "workspace", className: "workspace" }, [
      h(LeftPanel, {
        key: "left",
        catalog: state.catalog,
        templateId: state.templateId,
        setTemplateId: state.setTemplateId,
      }),
      h(Canvas, {
        key: "canvas",
        compiling: state.compiling,
        displayEdges: state.displayEdges,
        displayNodes: state.displayNodes,
        error: state.error,
        isValidConnection: state.isValidConnection,
        loading: state.loading,
        notice: state.notice,
        onCanvasDragOver: state.onCanvasDragOver,
        onCanvasDrop: state.onCanvasDrop,
        onConnect: state.onConnect,
        onEdgesChange: state.onEdgesChange,
        onNodesChange: state.onNodesChange,
        onSelectionChange: state.onSelectionChange,
        payload: state.payload,
        templateId: state.templateId,
      }),
      h(RightPanel, {
        key: "right",
        clearEdges: state.clearEdges,
        payload: state.payload,
        selectedEdge: state.selectedEdge,
        selectedNode: state.selectedNode,
      }),
    ]),
  ]);
}

createRoot(document.getElementById("root")).render(h(App));
