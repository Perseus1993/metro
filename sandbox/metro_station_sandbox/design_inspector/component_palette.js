const DRAG_TYPE = "application/metro-station-component";
const GRID_SIZE_M = 0.5;

export function componentDragPayload(component) {
  return JSON.stringify(component);
}

export function readDraggedComponent(event) {
  const raw = event.dataTransfer?.getData(DRAG_TYPE);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
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
  const size = component.size_m || {};
  const width = Number(size.width || 4);
  const height = Number(size.height || 3);
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
    ports: portsForComponent(component, levelFrame.levelId, geometry),
    geometry,
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
    width,
    height,
    style: { width, height },
    data,
    draggable: true,
    selectable: true,
  };
}

export function levelFrameForPosition(nodes, flowPosition) {
  const frames = nodes
    .filter((node) => node.type === "levelGroup")
    .map((node) => {
      const width = Number(node.style?.width || node.width || 0);
      const height = Number(node.style?.height || node.height || 0);
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      return {
        id: node.id,
        levelId: node.data?.level_id || String(node.id).replace(/^level:/, ""),
        x,
        y,
        width,
        height,
      };
    });

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
  return frames.sort(
    (left, right) =>
      distanceToFrame(left, flowPosition) - distanceToFrame(right, flowPosition),
  )[0] || null;
}

function portsForComponent(component, levelId, geometry) {
  const center = [
    geometry.x_m + geometry.width_m / 2,
    geometry.y_m + geometry.height_m / 2,
  ];
  if (component.kind === "gate") {
    return [
      port("service", "service", "in", levelId, center),
      port("release", "release", "out", levelId, center),
      port("paid", "walk", "bidirectional", levelId, center),
      port("unpaid", "walk", "out", levelId, center),
    ];
  }
  if (["entrance", "platform_edge"].includes(component.kind)) {
    return [port("walk", "walk", "bidirectional", levelId, center)];
  }
  return [];
}

function port(id, kind, direction, levelId, position) {
  return {
    id,
    kind,
    direction,
    level_id: levelId,
    position_m: position,
    label: "",
    metadata: {},
  };
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

function distanceToFrame(frame, point) {
  const cx = frame.x + frame.width / 2;
  const cy = frame.y + frame.height / 2;
  return (point.x - cx) ** 2 + (point.y - cy) ** 2;
}
