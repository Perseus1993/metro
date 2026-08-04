import { MarkerType } from "@xyflow/react";

export function decorateEdges(edges, payload) {
  const graph = payload?.graph || {};
  const connectionStatus = graph.connection_status || {};
  const severityByConnection = diagnosticsByConnection(graph.diagnostics || []);

  return edges.map((edge) => {
    const connectionId = stripEdgePrefix(edge.id);
    const severity = severityByConnection.get(connectionId);
    const status = connectionStatus[connectionId];
    const className = edgeClassName(edge, severity, status);
    const color = edgeColor(className);
    const bidirectional = edge.data?.bidirectional !== false;
    return {
      ...edge,
      className,
      animated: false,
      interactionWidth: 16,
      zIndex: edge.data?.kind === "vertical" ? -2 : -1,
      style: { strokeWidth: 1.1, stroke: color },
      markerEnd: bidirectional ? undefined : { type: MarkerType.ArrowClosed, color },
      data: {
        ...(edge.data || {}),
        inspectorStatus: status ? "design_connection" : severity || "pending",
      },
    };
  });
}

export function validateConnection(nodes, edges, connection) {
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target || source.id === target.id) {
    return false;
  }
  if (!source.id.startsWith("element:") || !target.id.startsWith("element:")) {
    return false;
  }
  const sourcePort = findPort(source, connection.sourceHandle);
  const targetPort = findPort(target, connection.targetHandle);
  if (!sourcePort || !targetPort) {
    return false;
  }
  if (sourcePort.direction === "in" || targetPort.direction === "out") {
    return false;
  }
  return !edges.some(
    (edge) =>
      edge.source === connection.source &&
      edge.target === connection.target &&
      edge.sourceHandle === connection.sourceHandle &&
      edge.targetHandle === connection.targetHandle,
  );
}

export function inferConnectionData(nodes, connection) {
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  const sourcePort = findPort(source, connection.sourceHandle);
  const targetPort = findPort(target, connection.targetHandle);
  const vertical = sourcePort?.kind === "vertical" || targetPort?.kind === "vertical";
  return {
    kind: vertical ? "vertical" : "walk",
    bidirectional:
      sourcePort?.direction === "bidirectional" && targetPort?.direction === "bidirectional",
    metadata: { inspector_created: true },
  };
}

export function slimEdges(edges) {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle,
    targetHandle: edge.targetHandle,
    data: edge.data,
  }));
}

function diagnosticsByConnection(diagnostics) {
  const severityByConnection = new Map();
  diagnostics.forEach((item) => {
    if (!item.connection_id) {
      return;
    }
    const previous = severityByConnection.get(item.connection_id);
    if (severityRank(item.severity) > severityRank(previous)) {
      severityByConnection.set(item.connection_id, item.severity);
    }
  });
  return severityByConnection;
}

function findPort(node, handleId) {
  if (!node || !handleId) {
    return null;
  }
  return (node.data?.ports || []).find((port) => port.id === handleId) || null;
}

function stripEdgePrefix(edgeId) {
  return String(edgeId || "").replace(/^edge:/, "");
}

function edgeClassName(edge, severity, status) {
  const parts = [];
  if (severity === "error") {
    parts.push("edge-error");
  } else if (severity === "warning") {
    parts.push("edge-warning");
  } else if (status) {
    parts.push("edge-ok");
  } else {
    parts.push("edge-warning");
  }
  if (edge.data?.draft) {
    parts.push("edge-draft");
  }
  if (edge.data?.kind === "vertical") {
    parts.push("edge-vertical");
  }
  if (
    String(edge.sourceHandle || "").startsWith("level:") ||
    String(edge.targetHandle || "").startsWith("level:")
  ) {
    parts.push("edge-level-transfer");
  }
  return parts.join(" ");
}

function edgeColor(className) {
  if (className.includes("edge-error")) {
    return "#b43131";
  }
  if (className.includes("edge-warning")) {
    return "#a96300";
  }
  return "#16695a";
}

function severityRank(severity) {
  if (severity === "error") {
    return 3;
  }
  if (severity === "warning") {
    return 2;
  }
  if (severity === "info") {
    return 1;
  }
  return 0;
}
