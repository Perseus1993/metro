const DRAG_TYPE = "application/metro-station-component";
const GRID_SIZE_M = 0.5;
const EDITOR_UNITS_PER_METER = 1;

export function componentDragPayload(component) {
  return JSON.stringify(component);
}

export function readDraggedComponent(event) {
  const raw = event.dataTransfer?.getData(DRAG_TYPE);
  if (!raw) {
    return null;
  }
  try {
    return normalizeComponent(JSON.parse(raw));
  } catch {
    return null;
  }
}

export function beginComponentDrag(event, component) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData(DRAG_TYPE, componentDragPayload(component));
}

export function acceptsComponentDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes(DRAG_TYPE);
}

export function createPaletteNode(component, levelFrame, flowPosition, existingNodes) {
  component = normalizeComponent(component);
  if (!component) {
    return null;
  }
  const size = component.size_m || {};
  const width = metricSize(size.width, 4);
  const height = metricSize(size.height, 3);
  const x = clampToLevel(snap(flowPosition.x - levelFrame.x - width / 2), width, levelFrame.width);
  const y = clampToLevel(snap(flowPosition.y - levelFrame.y - height / 2), height, levelFrame.height);
  const geometry = {
    shape: "rect",
    x_m: x,
    y_m: y,
    width_m: width,
    height_m: height,
    rotation_deg: 0,
    points_m: [],
  };
  const elementId = uniqueElementId(component.kind, x, y, existingNodes);
  const connectsLevels = connectsLevelIdsForComponent(component, levelFrame, existingNodes);
  if (component.role === "vertical_connector" && connectsLevels.length < 2) {
    return null;
  }
  const data = {
    inspector_created: true,
    palette_id: component.id,
    element_id: elementId,
    kind: component.kind,
    level_id: levelFrame.levelId,
    role: component.role || "facility",
    label: component.label || component.kind,
    capacity: component.capacity || null,
    queue_policy: {},
    ports: portsForComponent(component, levelFrame.levelId, geometry, connectsLevels, elementId),
    geometry,
    connects_levels: connectsLevels,
    gate_direction: component.gate_direction || null,
    direction: component.direction || null,
    line_id: component.line_id || null,
    metadata: {
      inspector_created: true,
      palette_id: component.id,
    },
  };

  return {
    id: `element:${elementId}`,
    type: component.node_type || "facilityNode",
    parentId: levelFrame.id,
    extent: "parent",
    position: { x, y },
    width: toEditorUnits(width),
    height: toEditorUnits(height),
    style: { width: toEditorUnits(width), height: toEditorUnits(height) },
    data,
    draggable: true,
    selectable: true,
  };
}

export function levelFrameForPosition(nodes, flowPosition) {
  const frames = levelFrames(nodes);

  const containing = frames.find(
    (frame) =>
      flowPosition.x >= frame.x &&
      flowPosition.x <= frame.x + frame.width &&
      flowPosition.y >= frame.y &&
      flowPosition.y <= frame.y + frame.height,
  );
  if (containing) {
    return containing;
  }
  return null;
}

function portsForComponent(component, levelId, geometry, connectsLevels, elementId) {
  if (component.kind === "gate") {
    return [
      port("service", "service", "in", levelId, sidePoint(geometry, "left", 0.3)),
      port("release", "release", "out", levelId, sidePoint(geometry, "right", 0.3)),
      port(
        "paid",
        "walk",
        "bidirectional",
        levelId,
        sidePoint(geometry, "right", 0.72),
        { graph_node_id: `gate:${elementId}:paid` },
      ),
      port(
        "unpaid",
        "walk",
        "bidirectional",
        levelId,
        sidePoint(geometry, "left", 0.72),
        { graph_node_id: `gate:${elementId}:unpaid` },
      ),
    ];
  }
  if (component.role === "vertical_connector") {
    return connectsLevels.map((connectedLevelId, index) =>
      port(
        `level:${connectedLevelId}`,
        "vertical",
        "bidirectional",
        connectedLevelId,
        verticalPortPoint(geometry, index, connectsLevels.length),
      ),
    );
  }
  if (["entrance", "platform_edge"].includes(component.kind)) {
    return [port("walk", "walk", "bidirectional", levelId, centerPoint(geometry))];
  }
  return [];
}

function port(id, kind, direction, levelId, position, metadata = {}) {
  return {
    id,
    kind,
    direction,
    level_id: levelId,
    position_m: position,
    label: "",
    metadata,
  };
}

function connectsLevelIdsForComponent(component, levelFrame, nodes) {
  if (component.role !== "vertical_connector") {
    return [];
  }
  const frames = levelFrames(nodes).sort((left, right) => left.y - right.y);
  const currentIndex = frames.findIndex((frame) => frame.id === levelFrame.id);
  if (currentIndex < 0) {
    return [];
  }
  const adjacentIndex = adjacentLevelIndex(frames, currentIndex, component.direction);
  if (adjacentIndex < 0) {
    return [];
  }
  return [frames[currentIndex], frames[adjacentIndex]]
    .sort((left, right) => left.y - right.y)
    .map((frame) => frame.levelId);
}

function adjacentLevelIndex(frames, currentIndex, direction) {
  if (direction === "down" && currentIndex < frames.length - 1) {
    return currentIndex + 1;
  }
  if (direction === "up" && currentIndex > 0) {
    return currentIndex - 1;
  }
  const lowerIndex = currentIndex < frames.length - 1 ? currentIndex + 1 : -1;
  if (lowerIndex >= 0) {
    return lowerIndex;
  }
  return currentIndex > 0 ? currentIndex - 1 : -1;
}

function levelFrames(nodes) {
  return nodes
    .filter((node) => node.type === "levelGroup")
    .map((node) => {
      const width = Number(node.style?.width || node.width || 0);
      const height = Number(node.style?.height || node.height || 0);
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      return {
        id: node.id,
        levelId: node.data?.level_id || String(node.id).replace(/^level:/, ""),
        label: node.data?.label || node.data?.level_id || String(node.id).replace(/^level:/, ""),
        x,
        y,
        width,
        height,
      };
    })
    .filter((frame) => frame.width > 0 && frame.height > 0);
}

function centerPoint(geometry) {
  return [
    geometry.x_m + geometry.width_m / 2,
    geometry.y_m + geometry.height_m / 2,
  ];
}

function sidePoint(geometry, side, ratio) {
  const y = geometry.y_m + geometry.height_m * ratio;
  if (side === "left") {
    return [geometry.x_m, y];
  }
  return [geometry.x_m + geometry.width_m, y];
}

function verticalPortPoint(geometry, index, total) {
  if (total <= 1) {
    return centerPoint(geometry);
  }
  return [
    geometry.x_m + geometry.width_m / 2,
    geometry.y_m + geometry.height_m * (index / (total - 1)),
  ];
}

function uniqueElementId(kind, x, y, nodes) {
  const stem = `draft_${kind}_${Date.now().toString(36)}_${Math.round(x * 10)}_${Math.round(y * 10)}`;
  const knownIds = new Set(nodes.map((node) => node.id));
  let candidate = stem;
  let index = 2;
  while (knownIds.has(`element:${candidate}`)) {
    candidate = `${stem}_${index}`;
    index += 1;
  }
  return candidate;
}

function snap(value) {
  return Math.round(value / GRID_SIZE_M) * GRID_SIZE_M;
}

function clampToLevel(value, size, maxSize) {
  return Math.max(0, Math.min(value, Math.max(0, maxSize - size)));
}

function metricSize(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function normalizeComponent(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  if (!payload.id || !payload.kind || typeof payload.id !== "string" || typeof payload.kind !== "string") {
    return null;
  }
  const size = payload.size_m || {};
  const width = Number(size.width);
  const height = Number(size.height);
  if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
    return null;
  }
  return payload;
}

function toEditorUnits(meters) {
  return meters * EDITOR_UNITS_PER_METER;
}
