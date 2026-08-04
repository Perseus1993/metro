import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
} from "@xyflow/react";

import { fetchJson } from "./api.js?v=debug-log-1";
import { stationBuildProgress } from "./build_progress.js?v=guided-builder-1";
import { recordDebugEvent } from "./debug_event_log.js?v=debug-log-1";
import {
  acceptsComponentDrag,
  createPaletteNode,
  levelFrameForPosition,
  readDraggedComponent,
} from "./component_palette.js?v=flexible-layout-1";
import {
  decorateEdges,
  inferConnectionData,
  slimEdges,
  validateConnection,
} from "./flow_edges.js?v=ops-config-1";
import {
  acceptsDemandFlowDrag,
  createDemandFlowNode,
  createSuggestedDemandFlowNode,
  demandFlowSourceAt,
  readDraggedDemandFlow,
  updateDemandFlowRate,
  updateDemandFlowTarget,
  updateDemandFlowTotal,
} from "./demand_flow_palette.js?v=station-builder-1";
import {
  applyInspectorDimensions,
  decorateNodes,
  moveAttachedQueues,
  normalizeEdges,
  normalizeNodes,
  slimNodes,
} from "./flow_state.js?v=flexible-layout-1";
import { createSuggestedComponentNode } from "./guided_placement.js?v=guided-builder-1";
import {
  createStationSetupNodes,
  normalizeStationSetup,
  stationSetupTemplateId,
} from "./station_setup.js?v=station-setup-1";

export function useStationInspectorState(defaultTemplateId) {
  const { screenToFlowPosition } = useReactFlow();
  const [catalog, setCatalog] = useState(null);
  const [templateId, setTemplateId] = useState(defaultTemplateId);
  const [payload, setPayload] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [operations, setOperations] = useState({});
  const [canvasMode, setCanvasMode] = useState("overview");
  const [selection, setSelection] = useState({ nodeId: null, edgeId: null });
  const [loading, setLoading] = useState(true);
  const [compiling, setCompiling] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [simulating, setSimulating] = useState(false);
  const [simProgress, setSimProgress] = useState(null);
  const [simResult, setSimResult] = useState(null);
  const [draftVersion, setDraftVersion] = useState(0);
  const [compiledVersion, setCompiledVersion] = useState(0);
  const [stationGenerated, setStationGenerated] = useState(false);
  const [stationSetup, setStationSetup] = useState(null);
  const [setupOpen, setSetupOpen] = useState(true);
  const [setupCompleted, setSetupCompleted] = useState(false);
  const pollTimerRef = useRef(null);
  const compileTimerRef = useRef(null);
  const compilingRef = useRef(false);
  const pendingCompileRef = useRef(null);
  const compileInvokerRef = useRef(null);
  const compileAbortRef = useRef(null);
  const designLoadAbortRef = useRef(null);
  const pendingSetupRef = useRef(null);
  const mountedRef = useRef(true);
  const draftVersionRef = useRef(0);
  const compileRequestRef = useRef(0);
  const designLoadRequestRef = useRef(0);
  const stationGeneratedRef = useRef(false);

  const markDraftChanged = useCallback(() => {
    draftVersionRef.current += 1;
    setDraftVersion(draftVersionRef.current);
  }, []);

  useEffect(() => {
    fetchJson("/api/templates")
      .then((data) => {
        if (!mountedRef.current) {
          return;
        }
        setCatalog(data);
        setTemplateId(data.default_template_id || defaultTemplateId);
      })
      .catch((exc) => {
        if (mountedRef.current) {
          setError(String(exc));
        }
      });
  }, [defaultTemplateId]);

  const loadDesign = useCallback((nextTemplateId) => {
    if (compileAbortRef.current !== null) {
      compileAbortRef.current.abort();
      compileAbortRef.current = null;
    }
    if (designLoadAbortRef.current !== null) {
      designLoadAbortRef.current.abort();
    }
    const designLoadRequestId = designLoadRequestRef.current + 1;
    const designLoadAbortController = new AbortController();
    designLoadRequestRef.current = designLoadRequestId;
    designLoadAbortRef.current = designLoadAbortController;
    compileRequestRef.current += 1;
    compilingRef.current = false;
    pendingCompileRef.current = null;
    setCompiling(false);
    draftVersionRef.current = 0;
    setDraftVersion(0);
    setCompiledVersion(0);
    setStationGenerated(false);
    stationGeneratedRef.current = false;
    setLoading(true);
    setReady(false);
    setSelection({ nodeId: null, edgeId: null });
    fetchJson(`/api/design?template=${encodeURIComponent(nextTemplateId)}`, {
      signal: designLoadAbortController.signal,
    })
      .then((data) => {
        if (!isCurrentDesignLoad()) {
          return;
        }
        const reactFlow = data.react_flow || {};
        let nextNodes = normalizeNodes(reactFlow.nodes || []);
        let nextError = "";
        let nextNotice = "";
        const pendingSetup = pendingSetupRef.current;
        if (pendingSetup?.templateId === nextTemplateId) {
          const created = createStationSetupNodes(
            nextNodes,
            pendingSetup.componentPalette,
            pendingSetup.config,
          );
          pendingSetupRef.current = null;
          if (created.error) {
            nextError = created.error;
            setSetupOpen(true);
            recordDebugEvent(
              "setup.auto_layout_failed",
              { config: pendingSetup.config, error: created.error },
              "error",
            );
          } else {
            nextNodes = created.nodes;
            draftVersionRef.current = 1;
            setDraftVersion(1);
            setStationSetup(created.config);
            setSetupCompleted(true);
            nextNotice = "基础站点已自动放好。现在可以拖动设施微调，或直接定义客流。";
            recordDebugEvent(
              "setup.auto_layout_completed",
              {
                config: created.config,
                counts: created.counts,
                element_ids: created.nodes
                  .filter((node) => node.data?.inspector_created)
                  .map((node) => node.data?.element_id),
              },
              "ok",
            );
          }
        }
        setPayload(data);
        setNodes(nextNodes);
        setEdges(normalizeEdges(reactFlow.edges || []));
        setOperations(data.operations || {});
        const generated = data.document?.metadata?.generation_state === "generated";
        stationGeneratedRef.current = generated;
        setStationGenerated(generated);
        setError(nextError);
        setNotice(nextNotice);
        setReady(true);
      })
      .catch((exc) => {
        if (!isCurrentDesignLoad() || exc?.name === "AbortError") {
          return;
        }
        setError(String(exc));
        setReady(false);
      })
      .finally(() => {
        if (isCurrentDesignLoad()) {
          designLoadAbortRef.current = null;
          setLoading(false);
        }
      });

    function isCurrentDesignLoad() {
      return (
        mountedRef.current &&
        designLoadRequestId === designLoadRequestRef.current
      );
    }
  }, []);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
      }
      if (compileTimerRef.current !== null) {
        window.clearTimeout(compileTimerRef.current);
      }
      if (compileAbortRef.current !== null) {
        compileAbortRef.current.abort();
        compileAbortRef.current = null;
      }
      if (designLoadAbortRef.current !== null) {
        designLoadAbortRef.current.abort();
        designLoadAbortRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (templateId) {
      loadDesign(templateId);
    }
  }, [templateId, loadDesign]);

  const requestCompile = useCallback(({ generate, syncFlow }) => {
    if (!ready || loading) {
      return;
    }
    if (compilingRef.current) {
      pendingCompileRef.current = { generate, syncFlow };
      return;
    }
    const requestVersion = draftVersionRef.current;
    const requestId = compileRequestRef.current + 1;
    const abortController = new AbortController();
    compileRequestRef.current = requestId;
    compileAbortRef.current = abortController;
    compilingRef.current = true;
    setCompiling(true);
    recordDebugEvent(generate ? "station.generate_dispatched" : "design.compile_dispatched", {
      request_version: requestVersion,
      node_count: nodes.length,
      edge_count: edges.length,
      generate_station: Boolean(generate),
    });
    fetchJson("/api/compile", {
      method: "POST",
      signal: abortController.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_id: templateId,
        nodes: slimNodes(nodes),
        edges: slimEdges(edges),
        operations,
        generate_station: Boolean(generate),
      }),
    })
      .then((data) => {
        if (!isCurrentCompileRequest()) {
          return;
        }
        setPayload(data);
        setCompiledVersion(requestVersion);
        if (generate) {
          stationGeneratedRef.current = true;
          setStationGenerated(true);
        }
        if (syncFlow) {
          const reactFlow = data.react_flow || {};
          const demandNodes = nodes.filter((node) => node.data?.demand_flow);
          setNodes([...normalizeNodes(reactFlow.nodes || []), ...demandNodes]);
          setEdges(normalizeEdges(reactFlow.edges || []));
        }
        setOperations((current) =>
          sameOperationValues(current, data.operations) ? current : data.operations || current,
        );
        setError("");
      })
      .catch((exc) => {
        if (isCurrentCompileRequest() && exc?.name !== "AbortError") {
          setError(String(exc));
        }
      })
      .finally(() => {
        if (requestId === compileRequestRef.current) {
          if (compileAbortRef.current === abortController) {
            compileAbortRef.current = null;
          }
          compilingRef.current = false;
          const pending = pendingCompileRef.current;
          pendingCompileRef.current = null;
          if (!mountedRef.current) {
            return;
          }
          if (pending !== null && compileInvokerRef.current !== null) {
            compileInvokerRef.current(pending);
          } else {
            setCompiling(false);
          }
        }
      });

    function isCurrentCompileRequest() {
      return (
        mountedRef.current &&
        requestId === compileRequestRef.current &&
        requestVersion === draftVersionRef.current
      );
    }
  }, [edges, loading, nodes, operations, ready, templateId]);
  compileInvokerRef.current = requestCompile;

  const compileDraft = useCallback(() => {
    requestCompile({ generate: stationGeneratedRef.current, syncFlow: false });
  }, [requestCompile]);

  const generateStation = useCallback(() => {
    if (compileTimerRef.current !== null) {
      window.clearTimeout(compileTimerRef.current);
      compileTimerRef.current = null;
    }
    recordDebugEvent("station.generate_clicked", {
      template_id: templateId,
      node_count: nodes.length,
      edge_count: edges.length,
    });
    stationGeneratedRef.current = true;
    requestCompile({ generate: true, syncFlow: true });
  }, [edges.length, nodes.length, requestCompile, templateId]);

  useEffect(() => {
    if (!ready || loading) {
      return undefined;
    }
    compileTimerRef.current = window.setTimeout(() => {
      compileTimerRef.current = null;
      compileDraft();
    }, 420);
    return () => {
      if (compileTimerRef.current !== null) {
        window.clearTimeout(compileTimerRef.current);
        compileTimerRef.current = null;
      }
    };
  }, [compileDraft, loading, ready]);

  const visibleNodes = useMemo(() => visibleNodesForCanvas(nodes, canvasMode), [canvasMode, nodes]);
  const visibleNodeIds = useMemo(
    () => new Set(visibleNodes.map((node) => node.id)),
    [visibleNodes],
  );
  const visibleEdges = useMemo(
    () =>
      canvasMode === "connections"
        ? edges.filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
        : [],
    [canvasMode, edges, visibleNodeIds],
  );
  const displayNodes = useMemo(() => decorateNodes(visibleNodes), [visibleNodes]);
  const displayEdges = useMemo(() => decorateEdges(visibleEdges, payload), [payload, visibleEdges]);
  const selectedNode = displayNodes.find((node) => node.id === selection.nodeId) || null;
  const selectedEdge = displayEdges.find((edge) => edge.id === selection.edgeId) || null;
  const platformOptions = useMemo(
    () =>
      nodes
        .filter((node) => node.data?.kind === "platform_edge")
        .map((node) => ({
          id: String(node.id).replace(/^element:/, ""),
          label: node.data?.label || node.data?.element_id || node.id,
          lineId: node.data?.line_id || "-",
          direction: node.data?.direction || "-",
        })),
    [nodes],
  );
  const buildProgress = useMemo(
    () => stationBuildProgress(nodes, payload, stationGenerated),
    [nodes, payload, stationGenerated],
  );

  const onNodesChange = useCallback((changes) => {
    setNodes((current) => applyInspectorNodeChanges(changes, current));
    const mutations = changes.filter(isNodeDraftMutation);
    if (mutations.length) {
      markDraftChanged();
    }
    const debugChanges = completedNodeChanges(mutations);
    if (debugChanges.length) {
      recordDebugEvent("layout.nodes_changed", { changes: debugChanges });
    }
  }, [markDraftChanged]);

  const onEdgesChange = useCallback((changes) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    if (changes.some((change) => change.type !== "select")) {
      markDraftChanged();
      recordDebugEvent("layout.edges_changed", {
        changes: changes
          .filter((change) => change.type !== "select")
          .map(compactFlowChange),
      });
    }
  }, [markDraftChanged]);

  const onCanvasDragOver = useCallback((event) => {
    if (!acceptsComponentDrag(event) && !acceptsDemandFlowDrag(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const addSuggestedComponent = useCallback((component) => {
    const created = createSuggestedComponentNode(component, nodes);
    if (!created.node) {
      setError(created.error);
      setNotice("");
      recordDebugEvent(
        "facility.add_failed",
        { component_id: component.id, error: created.error },
        "error",
      );
      return;
    }
    setNodes((current) => [...current, created.node]);
    markDraftChanged();
    setSelection({ nodeId: created.node.id, edgeId: null });
    setError("");
    setNotice(`已自动放置：${component.label || component.kind}。可直接拖动微调。`);
    recordDebugEvent("facility.added_by_click", {
      component_id: component.id,
      node: debugNodeSnapshot(created.node),
    });
  }, [markDraftChanged, nodes]);

  const addSuggestedDemandFlow = useCallback((flow) => {
    const created = createSuggestedDemandFlowNode(flow, operations, nodes);
    if (!created.node) {
      setError(created.error);
      setNotice("");
      recordDebugEvent(
        "demand.add_failed",
        { flow_id: flow.id, error: created.error },
        "error",
      );
      return;
    }
    setNodes((current) => [...current, created.node]);
    markDraftChanged();
    setSelection({ nodeId: created.node.id, edgeId: null });
    setError("");
    setNotice(`已绑定客流：${flow.label}。选中客流卡可修改流量。`);
    recordDebugEvent("demand.added_by_click", {
      flow_id: flow.id,
      node: debugNodeSnapshot(created.node),
    });
  }, [markDraftChanged, nodes, operations]);

  const onCanvasDrop = useCallback(
    (event) => {
      const demandFlow = readDraggedDemandFlow(event);
      if (demandFlow) {
        event.preventDefault();
        const flowPosition = screenToFlowPosition({ x: event.clientX, y: event.clientY });
        const preferredNodeId = event.target
          ?.closest?.(".react-flow__node")
          ?.getAttribute("data-id");
        const source = demandFlowSourceAt(nodes, flowPosition, preferredNodeId);
        const created = createDemandFlowNode(demandFlow, source, operations, nodes);
        if (!created.node) {
          setError(created.error);
          setNotice("");
          recordDebugEvent(
            "demand.drop_failed",
            { flow_id: demandFlow.id, error: created.error },
            "error",
          );
          return;
        }
        setNodes((current) => [...current, created.node]);
        markDraftChanged();
        setSelection({ nodeId: created.node.id, edgeId: null });
        setError("");
        setNotice(`Bound ${demandFlow.label} to ${source.data?.label || source.id}`);
        recordDebugEvent("demand.dropped", {
          flow_id: demandFlow.id,
          source_node_id: source.id,
          node: debugNodeSnapshot(created.node),
        });
        return;
      }
      const component = readDraggedComponent(event);
      if (!component) {
        return;
      }
      event.preventDefault();
      const flowPosition = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const levelFrame = levelFrameForPosition(nodes, flowPosition);
      if (!levelFrame) {
        setError("请把设施拖进可见的楼层矩形内；也可以直接点击左侧设施卡自动放置。");
        setNotice("");
        recordDebugEvent(
          "facility.drop_failed",
          { component_id: component.id, reason: "outside_level" },
          "error",
        );
        return;
      }
      const nextNode = createPaletteNode(component, levelFrame, flowPosition, nodes);
      if (!nextNode) {
        setError(`${component.label || component.kind}需要在这里连接一个相邻楼层。`);
        setNotice("");
        recordDebugEvent(
          "facility.drop_failed",
          { component_id: component.id, reason: "no_adjacent_level" },
          "error",
        );
        return;
      }
      setNodes((current) => [...current, nextNode]);
      markDraftChanged();
      setSelection({ nodeId: nextNode.id, edgeId: null });
      setError("");
      setNotice(`已放置${component.label || component.kind}到${levelFrame.label || levelFrame.levelId}`);
      recordDebugEvent("facility.dropped", {
        component_id: component.id,
        level_id: levelFrame.levelId,
        node: debugNodeSnapshot(nextNode),
      });
    },
    [markDraftChanged, nodes, operations, screenToFlowPosition],
  );

  const isValidConnection = useCallback(
    (connection) => validateConnection(nodes, edges, connection),
    [edges, nodes],
  );

  const onConnect = useCallback(
    (connection) => {
      if (!validateConnection(nodes, edges, connection)) {
        return;
      }
      setEdges((current) =>
        addEdge(
          {
            ...connection,
            id: `edge:draft_${Date.now()}`,
            type: "smoothstep",
            data: { ...inferConnectionData(nodes, connection), draft: true },
          },
          current,
        ),
      );
      markDraftChanged();
      recordDebugEvent("connection.created", { connection });
    },
    [edges, markDraftChanged, nodes],
  );

  const onSelectionChange = useCallback(({ nodes: selectedNodes, edges: selectedEdges }) => {
    const nextSelection = {
      nodeId: selectedNodes[0]?.id || null,
      edgeId: selectedEdges[0]?.id || null,
    };
    setSelection(nextSelection);
    recordDebugEvent("selection.changed", nextSelection);
  }, []);

  const deleteSelectedEdge = useCallback(() => {
    if (!selection.edgeId) {
      return;
    }
    setEdges((current) => current.filter((edge) => edge.id !== selection.edgeId));
    markDraftChanged();
    recordDebugEvent("connection.deleted", { edge_id: selection.edgeId });
    setSelection({ nodeId: selection.nodeId, edgeId: null });
  }, [markDraftChanged, selection.edgeId, selection.nodeId]);

  const clearEdges = useCallback(() => {
    setEdges([]);
    markDraftChanged();
    recordDebugEvent("connections.cleared", { edge_count: edges.length });
    setSelection({ nodeId: null, edgeId: null });
  }, [edges.length, markDraftChanged]);

  const onOperationChange = useCallback((fieldId, value) => {
    setOperations((current) => ({ ...current, [fieldId]: value }));
    setNodes((current) => updateDemandFlowTotal(current, fieldId, value));
    markDraftChanged();
    setNotice("");
    recordDebugEvent("simulation.parameter_changed", {
      field_id: fieldId,
      from: operations?.[fieldId],
      to: value,
    });
  }, [markDraftChanged, operations]);

  const onDemandFlowRateChange = useCallback((nodeId, value) => {
    setNodes((current) => updateDemandFlowRate(current, nodeId, value));
    markDraftChanged();
    setNotice("");
    const current = nodes.find((node) => node.id === nodeId);
    recordDebugEvent("demand.rate_changed", {
      node_id: nodeId,
      from: current?.data?.rate_per_hour,
      to: value,
    });
  }, [markDraftChanged, nodes]);

  const onDemandFlowTargetChange = useCallback((nodeId, targetElementId) => {
    setNodes((current) => updateDemandFlowTarget(current, nodeId, targetElementId));
    markDraftChanged();
    setNotice("");
    const current = nodes.find((node) => node.id === nodeId);
    recordDebugEvent("demand.target_changed", {
      node_id: nodeId,
      from: current?.data?.target_element_id,
      to: targetElementId,
    });
  }, [markDraftChanged, nodes]);

  const resetTemplate = useCallback(() => {
    loadDesign(templateId);
  }, [loadDesign, templateId]);

  const openSetupWizard = useCallback(() => {
    recordDebugEvent("setup.reconfigure_requested");
    setSetupOpen(true);
  }, []);

  const cancelSetupWizard = useCallback(() => {
    if (setupCompleted) {
      setSetupOpen(false);
    }
  }, [setupCompleted]);

  const startStationSetup = useCallback((config) => {
    try {
      const normalized = normalizeStationSetup(config);
      const nextTemplateId = stationSetupTemplateId(normalized.levels);
      const componentPalette = catalog?.component_palette || [];
      if (!componentPalette.length) {
        throw new Error("设施模板仍在加载，请稍后再试。");
      }
      pendingSetupRef.current = {
        componentPalette,
        config: normalized,
        templateId: nextTemplateId,
      };
      recordDebugEvent("setup.accepted", {
        config: normalized,
        template_id: nextTemplateId,
      });
      setSetupOpen(false);
      setError("");
      setNotice("正在按向导配置自动布置站点…");
      setSimResult(null);
      setSimProgress(null);
      if (nextTemplateId === templateId) {
        loadDesign(nextTemplateId);
      } else {
        setTemplateId(nextTemplateId);
      }
    } catch (exc) {
      setError(String(exc));
      setSetupOpen(true);
      recordDebugEvent("setup.rejected", { error: String(exc) }, "error");
    }
  }, [catalog, loadDesign, templateId]);

  const simulationBlocked =
    compiling ||
    draftVersion !== compiledVersion ||
    payload?.summary?.status === "error";
  const simulationBlockReason = compiling
    ? "布局正在校验，请稍候。"
    : draftVersion !== compiledVersion
      ? "最新拖动尚未完成校验。"
      : payload?.summary?.status === "error"
        ? "请先按左侧下一步提示或右侧诊断修复站点。"
        : "";

  const pollSimulationJob = useCallback((jobId) => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    const poll = () => {
      fetchJson(`/api/simulate/jobs/${encodeURIComponent(jobId)}`)
        .then((data) => {
          if (!mountedRef.current) {
            return;
          }
          setSimProgress(data);
          if (data.status === "queued" || data.status === "running") {
            pollTimerRef.current = window.setTimeout(poll, 500);
            return;
          }
          pollTimerRef.current = null;
          setSimResult(
            data.result || {
              status: "error",
              error: data.error || "Simulation failed",
              metrics: {},
              trajectory_report: null,
            },
          );
          setSimulating(false);
        })
        .catch((exc) => {
          if (!mountedRef.current) {
            return;
          }
          setSimResult({
            status: "error",
            error: String(exc),
            metrics: {},
            trajectory_report: null,
          });
          pollTimerRef.current = null;
          setSimulating(false);
        });
    };
    poll();
  }, []);

  const runSimulation = useCallback(() => {
    if (!ready || loading || simulating || simulationBlocked) {
      if (simulationBlocked) {
        setError(simulationBlockReason);
        setNotice("");
      }
      recordDebugEvent(
        "simulation.start_blocked",
        {
          ready,
          loading,
          simulating,
          simulation_blocked: simulationBlocked,
          reason: simulationBlockReason,
        },
        "error",
      );
      return;
    }
    setSimulating(true);
    recordDebugEvent("simulation.start_clicked", {
      template_id: templateId,
      node_count: nodes.length,
      edge_count: edges.length,
      operations,
    });
    setSimProgress({ status: "queued", step: 0, total_steps: 0, progress: 0 });
    setSimResult(null);
    fetchJson("/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_id: templateId,
        nodes: slimNodes(nodes),
        edges: slimEdges(edges),
        operations,
        entry_count_hour: Number(operations?.entry_count_hour ?? 4000),
        exit_count_hour: Number(operations?.exit_count_hour ?? 2000),
        transfer_count_hour: Number(operations?.transfer_count_hour ?? 0),
        minutes: Number(operations?.minutes ?? 1),
        seed: 42,
        generate_station: stationGenerated,
      }),
    })
      .then((data) => {
        if (!mountedRef.current) {
          return;
        }
        if (data.job_id) {
          setSimProgress(data);
          pollSimulationJob(data.job_id);
          return;
        }
        setSimResult(data);
        setSimProgress(null);
        setSimulating(false);
      })
      .catch((exc) => {
        if (!mountedRef.current) {
          return;
        }
        setSimResult({
          status: "error",
          error: String(exc),
          metrics: {},
          trajectory_report: null,
        });
        setSimProgress(null);
        setSimulating(false);
      });
  }, [
    edges,
    loading,
    nodes,
    operations,
    pollSimulationJob,
    ready,
    simulating,
    simulationBlocked,
    simulationBlockReason,
    stationGenerated,
    templateId,
  ]);

  const analysisDraft = useMemo(
    () => ({
      template_id: templateId,
      nodes: slimNodes(nodes),
      edges: slimEdges(edges),
      operations,
      generate_station: stationGenerated,
    }),
    [edges, nodes, operations, stationGenerated, templateId],
  );

  return {
    addSuggestedComponent,
    addSuggestedDemandFlow,
    analysisDraft,
    buildProgress,
    cancelSetupWizard,
    catalog,
    canvasMode,
    clearEdges,
    compileDraft,
    compiling,
    deleteSelectedEdge,
    displayEdges,
    displayNodes,
    error,
    generateStation,
    isValidConnection,
    loading,
    notice,
    onConnect,
    onCanvasDragOver,
    onCanvasDrop,
    onEdgesChange,
    onDemandFlowRateChange,
    onDemandFlowTargetChange,
    onNodesChange,
    onOperationChange,
    onSelectionChange,
    operationSchema: catalog?.operations_schema || [],
    operations,
    payload,
    platformOptions,
    openSetupWizard,
    resetTemplate,
    runSimulation,
    selectedEdge,
    selectedNode,
    setCanvasMode,
    setTemplateId,
    simProgress,
    simulationBlocked,
    simulationBlockReason,
    simulating,
    simResult,
    setupCompleted,
    setupOpen,
    startStationSetup,
    stationSetup,
    templateId,
  };
}

export function applyInspectorNodeChanges(changes, currentNodes) {
  const currentById = new Map(currentNodes.map((node) => [node.id, node]));
  const allowedChanges = changes.filter((change) => {
    if (change.type !== "remove") {
      return true;
    }
    return Boolean(currentById.get(change.id)?.data?.inspector_created);
  });
  const ownerDeltas = new Map();
  const ownerResizes = new Map();
  const resized = new Map();

  allowedChanges.forEach((change) => {
    const current = currentById.get(change.id);
    if (change.type === "position" && current && change.position) {
      const dx = Number(change.position.x || 0) - Number(current.position?.x || 0);
      const dy = Number(change.position.y || 0) - Number(current.position?.y || 0);
      if (dx !== 0 || dy !== 0) {
        ownerDeltas.set(String(change.id).replace(/^element:/, ""), { dx, dy });
      }
    }
    if (
      change.type === "dimensions" &&
      change.dimensions &&
      Object.prototype.hasOwnProperty.call(change, "resizing")
    ) {
      resized.set(change.id, change.dimensions);
      if (current && String(change.id).startsWith("element:")) {
        ownerResizes.set(String(change.id).replace(/^element:/, ""), {
          geometry: current.data?.geometry,
          oldWidth: Number(current.width || current.style?.width || change.dimensions.width),
          oldHeight: Number(current.height || current.style?.height || change.dimensions.height),
          newWidth: Number(change.dimensions.width),
          newHeight: Number(change.dimensions.height),
        });
      }
    }
  });

  const resizedNodes = applyNodeChanges(allowedChanges, currentNodes).map((node) => {
    let nextNode = node;
    const dimensions = resized.get(node.id);
    if (dimensions) {
      nextNode = applyInspectorDimensions(nextNode, dimensions);
    }

    return nextNode;
  });
  return moveAttachedQueues(resizedNodes, ownerDeltas, ownerResizes);
}

function isNodeDraftMutation(change) {
  if (change.type === "position") {
    return true;
  }
  if (change.type === "dimensions") {
    return Object.prototype.hasOwnProperty.call(change, "resizing");
  }
  return !["select"].includes(change.type);
}

function visibleNodesForCanvas(nodes, canvasMode) {
  if (canvasMode === "overview") {
    return nodes.filter((node) => node.type !== "queueLane" && node.type !== "queueGrid");
  }
  return nodes;
}

function sameOperationValues(left, right) {
  if (!right || typeof right !== "object") {
    return true;
  }
  const keys = new Set([...Object.keys(left || {}), ...Object.keys(right)]);
  for (const key of keys) {
    if (String(left?.[key] ?? "") !== String(right[key] ?? "")) {
      return false;
    }
  }
  return true;
}

function completedNodeChanges(changes) {
  return changes
    .filter((change) => {
      if (change.type === "position") return change.dragging !== true;
      if (change.type === "dimensions") return change.resizing !== true;
      return change.type !== "select";
    })
    .map(compactFlowChange);
}

function compactFlowChange(change) {
  return {
    type: change.type,
    id: change.id || null,
    position: change.position || null,
    dimensions: change.dimensions || null,
    item: change.item ? debugNodeSnapshot(change.item) : null,
  };
}

function debugNodeSnapshot(node) {
  return {
    id: node?.id || null,
    type: node?.type || null,
    parent_id: node?.parentId || null,
    position: node?.position || null,
    width: node?.width || node?.style?.width || null,
    height: node?.height || node?.style?.height || null,
    element_id: node?.data?.element_id || null,
    kind: node?.data?.kind || null,
    demand_flow: Boolean(node?.data?.demand_flow),
  };
}
