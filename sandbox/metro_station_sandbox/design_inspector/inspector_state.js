import {
  useCallback,
  useEffect,
  useMemo,
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
  const [selection, setSelection] = useState({ nodeId: null, edgeId: null });
  const [loading, setLoading] = useState(true);
  const [compiling, setCompiling] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    fetchJson("/api/templates")
      .then((data) => {
        setCatalog(data);
        setTemplateId(data.default_template_id || defaultTemplateId);
      })
      .catch((exc) => setError(String(exc)));
  }, [defaultTemplateId]);

  const loadDesign = useCallback((nextTemplateId) => {
    setLoading(true);
    setReady(false);
    setSelection({ nodeId: null, edgeId: null });
    fetchJson(`/api/design?template=${encodeURIComponent(nextTemplateId)}`)
      .then((data) => {
        setPayload(data);
        setNodes(normalizeNodes(data.react_flow.nodes));
        setEdges(normalizeEdges(data.react_flow.edges));
        setOperations(data.operations || {});
        setError("");
        setNotice("");
      })
      .catch((exc) => setError(String(exc)))
      .finally(() => {
        setLoading(false);
        setReady(true);
      });
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

  const displayNodes = useMemo(() => decorateNodes(nodes), [nodes]);
  const displayEdges = useMemo(() => decorateEdges(edges, payload), [edges, payload]);
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

  return {
    catalog,
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
    selectedEdge,
    selectedNode,
    setTemplateId,
    templateId,
  };
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
