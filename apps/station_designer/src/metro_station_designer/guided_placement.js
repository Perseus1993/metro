import {
  createPaletteNode,
  stationLevelFrames,
} from "./component_palette.js?v=guided-builder-1";

const HORIZONTAL_CENTERS = [8, 18, 28, 38, 48, 58, 68, 78, 88, 98, 108];
const VERTICAL_CENTERS = [16, 32, 48, 64];
const CLEARANCE_M = 1;

export function createSuggestedComponentNode(component, nodes, options = {}) {
  const frames = stationLevelFrames(nodes).sort((left, right) => left.y - right.y);
  if (!frames.length) {
    return { node: null, error: "请先选择一个空白站模板。" };
  }
  const frame = preferredFrame(component, frames, nodes, options);
  if (!frame) {
    return { node: null, error: "该设施在当前楼层结构中没有可连接的相邻楼层。" };
  }
  for (const center of placementCenters(component)) {
    const flowPosition = {
      x: frame.x + center.x,
      y: frame.y + center.y,
    };
    const node = createPaletteNode(component, frame, flowPosition, nodes);
    if (node && !overlapsExisting(node, nodes)) {
      return { node, error: "" };
    }
  }
  return {
    node: null,
    error: `本层没有足够空位自动放置${component.label || component.kind}，请拖动已有设施腾出空间。`,
  };
}

function preferredFrame(component, frames, nodes, options) {
  if (component.kind === "platform_edge") {
    return frames[frames.length - 1];
  }
  if (component.role !== "vertical_connector" || component.kind === "elevator") {
    return frames[0];
  }
  if (Number.isInteger(options.levelPairIndex)) {
    const pairIndex = options.levelPairIndex;
    if (pairIndex < 0 || pairIndex >= frames.length - 1) {
      return null;
    }
    return component.direction === "up" ? frames[pairIndex + 1] : frames[pairIndex];
  }
  const missingPair = firstPairNeedingComponent(component, frames, nodes);
  if (!missingPair) {
    return component.direction === "up" ? frames[frames.length - 1] : frames[0];
  }
  return component.direction === "up" ? missingPair.lower : missingPair.upper;
}

function firstPairNeedingComponent(component, frames, nodes) {
  const connectors = nodes.filter((node) => node.data?.role === "vertical_connector");
  for (let index = 0; index < frames.length - 1; index += 1) {
    const upper = frames[index];
    const lower = frames[index + 1];
    const requestedDirections =
      component.direction === "both" ? ["down", "up"] : [component.direction];
    const needsDirection = requestedDirections.some(
      (direction) => !pairHasDirection(connectors, upper, lower, direction),
    );
    if (needsDirection) {
      return { upper, lower };
    }
  }
  return null;
}

function pairHasDirection(connectors, upper, lower, direction) {
  return connectors.some((node) => {
    const levels = new Set(node.data?.connects_levels || []);
    if (!levels.has(upper.levelId) || !levels.has(lower.levelId)) {
      return false;
    }
    return node.data?.direction === "both" || node.data?.direction === direction;
  });
}

function placementCenters(component) {
  if (component.role === "vertical_connector") {
    return HORIZONTAL_CENTERS.flatMap((x) => [70, 54, 38, 22].map((y) => ({ x, y })));
  }
  if (component.kind === "platform_edge") {
    return HORIZONTAL_CENTERS.slice().reverse().flatMap((x) => [20, 34, 50].map((y) => ({ x, y })));
  }
  return VERTICAL_CENTERS.flatMap((y) => HORIZONTAL_CENTERS.map((x) => ({ x, y })));
}

function overlapsExisting(candidate, nodes) {
  const candidateBounds = nodeBounds(candidate);
  return nodes.some((node) => {
    if (!isBlockingEditorNode(node)) {
      return false;
    }
    if (!samePlacementPlane(candidate, node)) {
      return false;
    }
    return boundsOverlap(candidateBounds, nodeBounds(node), CLEARANCE_M);
  });
}

function isBlockingEditorNode(node) {
  return (
    String(node.id).startsWith("element:") &&
    node.data?.role !== "floor" &&
    !node.data?.demand_flow
  );
}

function samePlacementPlane(left, right) {
  if (left.data?.role === "vertical_connector" && right.data?.role === "vertical_connector") {
    return true;
  }
  return left.parentId === right.parentId;
}

function nodeBounds(node) {
  const x = Number(node.position?.x || 0);
  const y = Number(node.position?.y || 0);
  const width = Number(node.width || node.style?.width || 0);
  const height = Number(node.height || node.style?.height || 0);
  return { x, y, right: x + width, bottom: y + height };
}

function boundsOverlap(left, right, clearance) {
  return !(
    left.right + clearance <= right.x ||
    right.right + clearance <= left.x ||
    left.bottom + clearance <= right.y ||
    right.bottom + clearance <= left.y
  );
}
