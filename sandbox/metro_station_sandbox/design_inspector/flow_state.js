const EDITOR_UNITS_PER_METER = 1;

export function normalizeNodes(flowNodes) {
  return flowNodes.map((node) => applyDisplaySize({
    ...node,
    data: { ...(node.data || {}) },
  }));
}

export function normalizeEdges(flowEdges) {
  return flowEdges.map((edge) => ({
    ...edge,
    type: edge.type || "smoothstep",
    data: { ...(edge.data || {}) },
  }));
}

export function decorateNodes(nodes) {
  return nodes.map((node) => applyDisplaySize(node));
}

export function slimNodes(nodes) {
  return nodes.map((node) => ({
    id: node.id,
    type: node.type,
    parentId: node.parentId,
    position: node.position,
    width: node.width,
    height: node.height,
    style: {
      width: node.style?.width,
      height: node.style?.height,
    },
    data: node.data,
  }));
}

function applyDisplaySize(node) {
  const dimensions = nodeDimensions(node);
  const interaction = interactionSettings(node);
  return {
    ...node,
    ...interaction.node,
    width: dimensions.width,
    height: dimensions.height,
    style: {
      ...(node.style || {}),
      ...interaction.style,
      width: dimensions.width,
      height: dimensions.height,
    },
  };
}

function nodeDimensions(node) {
  const width = editorDimension(node.style?.width || node.width || 80);
  const height = editorDimension(node.style?.height || node.height || 34);
  const minimum = minimumDisplaySize(node);
  return {
    ...(node.style || {}),
    width: Math.max(width, minimum.width),
    height: Math.max(height, minimum.height),
  };
}

function minimumDisplaySize(node) {
  if (node.type === "levelGroup" || node.type === "floorZone") {
    return { width: 0, height: 0 };
  }
  if (node.type === "queueLane" || node.type === "queueGrid") {
    return { width: 3.0, height: 1.6 };
  }
  if (node.type === "verticalConnector") {
    return { width: 5.0, height: 5.0 };
  }
  if (node.data?.kind === "entrance") {
    return { width: 4.5, height: 4.5 };
  }
  if (node.data?.kind === "gate") {
    return { width: 8.0, height: 5.0 };
  }
  if (node.data?.kind === "platform_edge") {
    return { width: 6.0, height: 3.0 };
  }
  return { width: 4.0, height: 3.0 };
}

function interactionSettings(node) {
  if (node.type === "levelGroup") {
    return {
      node: { draggable: false, selectable: false, zIndex: -10 },
      style: { pointerEvents: "none" },
    };
  }
  if (node.type === "floorZone") {
    return {
      node: { draggable: false, selectable: false, zIndex: -8 },
      style: { pointerEvents: "none" },
    };
  }
  if (node.data?.kind === "obstacle" && !node.data?.inspector_created) {
    return {
      node: { draggable: false, selectable: false, zIndex: -4 },
      style: { pointerEvents: "none" },
    };
  }
  if (node.type === "queueLane" || node.type === "queueGrid") {
    return {
      node: { draggable: false, selectable: false, zIndex: -2 },
      style: { pointerEvents: "none" },
    };
  }
  return {
    node: { zIndex: 2 },
    style: {},
  };
}

function editorDimension(value) {
  const parsed = Number(value);
  const meters = Number.isFinite(parsed) ? parsed : 0;
  return meters * EDITOR_UNITS_PER_METER;
}
