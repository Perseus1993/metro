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

import { fetchJson } from "./api.js";
import {
  acceptsComponentDrag,
  createPaletteNode,
  levelFrameForPosition,
  readDraggedComponent,
} from "./component_palette.js";
import {
  decorateEdges,
  inferConnectionData,
  slimEdges,
  validateConnection,
} from "./flow_edges.js";
import {
  decorateNodes,
  normalizeEdges,
  normalizeNodes,
  slimNodes,
} from "./flow_state.js";

export function useStationInspectorState(defaultTemplateId) {
  const { screenToFlowPosition } = useReactFlow();
  const [catalog, setCatalog] = useState(null);
  const [templateId, setTemplateId] = useState(defaultTemplateId);
  const [payload, setPayload] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [selection, setSelection] = useState({ nodeId: null, edgeId: null });
  const [loading, setLoading] = useState(true);
  const [compiling, setCompiling] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

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
        setError("");
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
      }),
    })
      .then((data) => {
        setPayload(data);
        setError("");
      })
      .catch((exc) => setError(String(exc)))
      .finally(() => setCompiling(false));
  }, [edges, loading, nodes, ready, templateId]);

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
        setError("No level is available for this drop target.");
        return;
      }
      setNodes((current) => [
        ...current,
        createPaletteNode(component, levelFrame, flowPosition, current),
      ]);
      setError("");
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
    onConnect,
    onCanvasDragOver,
    onCanvasDrop,
    onEdgesChange,
    onNodesChange,
    onSelectionChange,
    payload,
    resetTemplate,
    selectedEdge,
    selectedNode,
    setTemplateId,
    templateId,
  };
}
