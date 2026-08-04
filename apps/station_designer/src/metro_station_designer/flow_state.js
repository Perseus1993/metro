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

export function moveAttachedQueues(nodes, ownerDeltas, ownerResizes = new Map()) {
  return nodes.map((node) => {
    if (!String(node.id).startsWith("queue:")) {
      return node;
    }
    const ownerId = node.data?.owner_element_id;
    const ownerDelta = ownerDeltas.get(ownerId) || { dx: 0, dy: 0 };
    const ownerResize = ownerResizes.get(ownerId);
    const resizeDelta = queueResizeAnchorDelta(node, ownerResize);
    const dx = ownerDelta.dx + resizeDelta.dx;
    const dy = ownerDelta.dy + resizeDelta.dy;
    if (dx === 0 && dy === 0) {
      return node;
    }
    return {
      ...node,
      position: {
        x: Number(node.position?.x || 0) + dx,
        y: Number(node.position?.y || 0) + dy,
      },
    };
  });
}

export function applyInspectorDimensions(node, dimensions) {
  const width = Number(dimensions.width);
  const height = Number(dimensions.height);
  return {
    ...node,
    width,
    height,
    style: {
      ...(node.style || {}),
      width,
      height,
    },
    data: {
      ...(node.data || {}),
      inspector_size_m: { width, height },
    },
  };
}

function queueResizeAnchorDelta(queueNode, ownerResize) {
  const servicePoint = queueNode.data?.service_point_m;
  const geometry = ownerResize?.geometry;
  if (!ownerResize || !Array.isArray(servicePoint) || !geometry) {
    return { dx: 0, dy: 0 };
  }
  const width = Number(geometry.width_m);
  const height = Number(geometry.height_m);
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    return { dx: 0, dy: 0 };
  }
  const xRatio = (Number(servicePoint[0]) - Number(geometry.x_m)) / width;
  const yRatio = (Number(servicePoint[1]) - Number(geometry.y_m)) / height;
  return {
    dx: xRatio * (ownerResize.newWidth - ownerResize.oldWidth),
    dy: yRatio * (ownerResize.newHeight - ownerResize.oldHeight),
  };
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
  if (node.type === "demandFlow") {
    return { width: 12, height: 5 };
  }
  if (node.type === "levelGroup" || node.type === "floorZone") {
    return { width: 0, height: 0 };
  }
  return { width: 0.5, height: 0.5 };
}

function interactionSettings(node) {
  if (node.type === "demandFlow") {
    return {
      node: { draggable: true, selectable: true, zIndex: 8 },
      style: {},
    };
  }
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
