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

import { fetchJson } from "./api.js?v=ops-config-1";
import {
  acceptsComponentDrag,
  createPaletteNode,
  levelFrameForPosition,
  readDraggedComponent,
} from "./component_palette.js?v=ops-config-1";
import {
  decorateEdges,
  inferConnectionData,
  slimEdges,
  validateConnection,
} from "./flow_edges.js?v=ops-config-1";
import {
  decorateNodes,
  normalizeEdges,
  normalizeNodes,
  slimNodes,
} from "./flow_state.js?v=ops-config-1";

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
  const pollTimerRef = useRef(null);
  const mountedRef = useRef(true);

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
    setLoading(true);
    setReady(false);
    setSelection({ nodeId: null, edgeId: null });
    fetchJson(`/api/design?template=${encodeURIComponent(nextTemplateId)}`)
      .then((data) => {
        if (!mountedRef.current) {
          return;
        }
        const reactFlow = data.react_flow || {};
        setPayload(data);
        setNodes(normalizeNodes(reactFlow.nodes || []));
        setEdges(normalizeEdges(reactFlow.edges || []));
        setOperations(data.operations || {});
        setError("");
        setNotice("");
        setReady(true);
      })
      .catch((exc) => {
        if (!mountedRef.current) {
          return;
        }
        setError(String(exc));
        setReady(false);
      })
      .finally(() => {
        if (mountedRef.current) {
          setLoading(false);
        }
      });
  }, []);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (templateId) {
      loadDesign(templateId);
    }
  }, [templateId, loadDesign]);

  const compileDraft = useCallback(() => {
    if (!ready || loading) {
      return;
    }
    setCompiling(true);
    fetchJson("/api/compile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_id: templateId,
        nodes: slimNodes(nodes),
        edges: slimEdges(edges),
        operations,
      }),
    })
      .then((data) => {
        setPayload(data);
        setOperations((current) =>
          sameOperationValues(current, data.operations) ? current : data.operations || current,
        );
        setError("");
      })
      .catch((exc) => setError(String(exc)))
      .finally(() => setCompiling(false));
  }, [edges, loading, nodes, operations, ready, templateId]);

  useEffect(() => {
    if (!ready || loading) {
      return undefined;
    }
    const timerId = window.setTimeout(compileDraft, 420);
    return () => window.clearTimeout(timerId);
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

  const onNodesChange = useCallback((changes) => {
    setNodes((current) => applyNodeChanges(changes, current));
  }, []);

  const onEdgesChange = useCallback((changes) => {
    setEdges((current) => applyEdgeChanges(changes, current));
  }, []);

  const onCanvasDragOver = useCallback((event) => {
    if (!acceptsComponentDrag(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const onCanvasDrop = useCallback(
    (event) => {
      const component = readDraggedComponent(event);
      if (!component) {
        return;
      }
      event.preventDefault();
      const flowPosition = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const levelFrame = levelFrameForPosition(nodes, flowPosition);
      if (!levelFrame) {
        setError("Drop components inside a visible station level.");
        setNotice("");
        return;
      }
      const nextNode = createPaletteNode(component, levelFrame, flowPosition, nodes);
      if (!nextNode) {
        setError(`${component.label || component.kind} needs an adjacent level here.`);
        setNotice("");
        return;
      }
      setNodes((current) => [...current, nextNode]);
      setSelection({ nodeId: nextNode.id, edgeId: null });
      setError("");
      setNotice(`Placed ${component.label || component.kind} on ${levelFrame.label || levelFrame.levelId}`);
    },
    [nodes, screenToFlowPosition],
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
    },
    [edges, nodes],
  );

  const onSelectionChange = useCallback(({ nodes: selectedNodes, edges: selectedEdges }) => {
    setSelection({
      nodeId: selectedNodes[0]?.id || null,
      edgeId: selectedEdges[0]?.id || null,
    });
  }, []);

  const deleteSelectedEdge = useCallback(() => {
    if (!selection.edgeId) {
      return;
    }
    setEdges((current) => current.filter((edge) => edge.id !== selection.edgeId));
    setSelection({ nodeId: selection.nodeId, edgeId: null });
  }, [selection.edgeId, selection.nodeId]);

  const clearEdges = useCallback(() => {
    setEdges([]);
    setSelection({ nodeId: null, edgeId: null });
  }, []);

  const onOperationChange = useCallback((fieldId, value) => {
    setOperations((current) => ({ ...current, [fieldId]: value }));
    setNotice("");
  }, []);

  const resetTemplate = useCallback(() => {
    loadDesign(templateId);
  }, [loadDesign, templateId]);

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
    if (!ready || loading || simulating) {
      return;
    }
    setSimulating(true);
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
        minutes: 1,
        seed: 42,
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
  }, [edges, loading, nodes, operations, pollSimulationJob, ready, simulating, templateId]);

  return {
    catalog,
    canvasMode,
    clearEdges,
    compileDraft,
    compiling,
    deleteSelectedEdge,
    displayEdges,
    displayNodes,
    error,
    isValidConnection,
    loading,
    notice,
    onConnect,
    onCanvasDragOver,
    onCanvasDrop,
    onEdgesChange,
    onNodesChange,
    onOperationChange,
    onSelectionChange,
    operationSchema: catalog?.operations_schema || [],
    operations,
    payload,
    resetTemplate,
    runSimulation,
    selectedEdge,
    selectedNode,
    setCanvasMode,
    setTemplateId,
    simProgress,
    simulating,
    simResult,
    templateId,
  };
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
