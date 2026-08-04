import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFlowProvider } from "@xyflow/react";

import { Canvas } from "./canvas.js?v=flexible-layout-1";
import { useStationInspectorState } from "./inspector_state.js?v=debug-log-1";
import { RightPanel } from "./right_panel.js?v=control-plan-1";
import { LeftPanel } from "./side_panel.js?v=station-setup-1";
import { StationSetupWizard } from "./station_setup_wizard.js?v=station-presets-1";
import { TopBar } from "./top_bar.js?v=station-setup-1";
import { useComparisonWorkflow } from "./use_comparison_workflow.js?v=control-plan-1";

const h = React.createElement;
const DEFAULT_TEMPLATE_ID = "scratch_single_level";

function App() {
  return h(ReactFlowProvider, null, h(StationDesignInspector));
}

function StationDesignInspector() {
  const state = useStationInspectorState(DEFAULT_TEMPLATE_ID);
  const comparison = useComparisonWorkflow(state.analysisDraft, state.payload?.control_catalog);

  return h("div", { className: "app" }, [
    h(TopBar, {
      key: "topbar",
      catalog: state.catalog,
      compiling: state.compiling,
      loading: state.loading,
      payload: state.payload,
      onCompile: state.compileDraft,
      onGenerate: state.generateStation,
      onDeleteSelectedEdge: state.deleteSelectedEdge,
      onNewStation: state.openSetupWizard,
      selectedEdge: state.selectedEdge,
    }),
    h("div", { key: "workspace", className: "workspace" }, [
      h(LeftPanel, {
        key: "left",
        buildProgress: state.buildProgress,
        catalog: state.catalog,
        onAddComponent: state.addSuggestedComponent,
        onAddDemandFlow: state.addSuggestedDemandFlow,
        onNewStation: state.openSetupWizard,
        stationSetup: state.stationSetup,
        templateId: state.templateId,
      }),
      h(Canvas, {
        key: "canvas",
        buildProgress: state.buildProgress,
        canvasMode: state.canvasMode,
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
        setCanvasMode: state.setCanvasMode,
        templateId: state.templateId,
      }),
      h(RightPanel, {
        key: "right",
        clearEdges: state.clearEdges,
        onDemandFlowRateChange: state.onDemandFlowRateChange,
        onDemandFlowTargetChange: state.onDemandFlowTargetChange,
        onOperationChange: state.onOperationChange,
        operationSchema: state.operationSchema,
        operations: state.operations,
        payload: state.payload,
        platformOptions: state.platformOptions,
        runSimulation: state.runSimulation,
        selectedEdge: state.selectedEdge,
        selectedNode: state.selectedNode,
        simProgress: state.simProgress,
        simResult: state.simResult,
        simulating: state.simulating,
        compiling: state.compiling,
        simulationBlocked: state.simulationBlocked,
        simulationBlockReason: state.simulationBlockReason,
        comparisonBlocked: state.simulationBlocked,
        comparisonWorkflow: comparison,
      }),
    ]),
    h(StationSetupWizard, {
      key: "setup-wizard",
      allowCancel: state.setupCompleted,
      catalogReady: Boolean(state.catalog) && !state.loading,
      onCancel: state.cancelSetupWizard,
      onStart: state.startStationSetup,
      open: state.setupOpen,
    }),
  ]);
}

createRoot(document.getElementById("root")).render(h(App));
