const DRAG_TYPE = "application/metro-passenger-flow";
const FLOW_WIDTH = 12;
const FLOW_HEIGHT = 5;

export {
  updateDemandFlowRate,
  updateDemandFlowTarget,
  updateDemandFlowTotal,
} from "./demand_flow_updates.js?v=guided-builder-1";

export function beginDemandFlowDrag(event, flow) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(flow));
}

export function acceptsDemandFlowDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes(DRAG_TYPE);
}

export function readDraggedDemandFlow(event) {
  const raw = event.dataTransfer?.getData(DRAG_TYPE);
  if (!raw) {
    return null;
  }
  try {
    const flow = JSON.parse(raw);
    return flow?.id && flow?.intent && flow?.source_kind ? flow : null;
  } catch {
    return null;
  }
}

export function demandFlowSourceAt(nodes, flowPosition, preferredNodeId = null) {
  const candidates = nodes.filter(
    (node) =>
      String(node.id).startsWith("element:") &&
      !node.data?.demand_flow &&
      node.data?.role !== "floor",
  );
  const preferred = candidates.find((node) => node.id === preferredNodeId);
  if (preferred) {
    return preferred;
  }
  const levelPositions = new Map(
    nodes
      .filter((node) => node.type === "levelGroup")
      .map((node) => [node.id, node.position || { x: 0, y: 0 }]),
  );
  return candidates.find((node) => {
    const parent = levelPositions.get(node.parentId) || { x: 0, y: 0 };
    const x = Number(parent.x || 0) + Number(node.position?.x || 0);
    const y = Number(parent.y || 0) + Number(node.position?.y || 0);
    const width = Number(node.width || node.style?.width || 0);
    const height = Number(node.height || node.style?.height || 0);
    return (
      flowPosition.x >= x &&
      flowPosition.x <= x + width &&
      flowPosition.y >= y &&
      flowPosition.y <= y + height
    );
  }) || null;
}

export function createDemandFlowNode(flow, sourceNode, operations, existingNodes) {
  if (!sourceNode || sourceNode.data?.kind !== flow.source_kind) {
    return {
      node: null,
      error: `${flow.label} must be dropped on a ${flow.source_kind}.`,
    };
  }
  const targetNode =
    flow.intent === "transfer" ? transferTargetFor(sourceNode, existingNodes) : null;
  if (flow.intent === "transfer" && !targetNode) {
    return {
      node: null,
      error: "Transfer flow needs another platform edge with a different service.",
    };
  }
  const levelNode = existingNodes.find((node) => node.id === sourceNode.parentId);
  const levelWidth = Number(levelNode?.style?.width || levelNode?.width || 120);
  const levelHeight = Number(levelNode?.style?.height || levelNode?.height || 80);
  const sourceWidth = Number(sourceNode.width || sourceNode.style?.width || 5);
  const x = Math.max(
    0,
    Math.min(Number(sourceNode.position?.x || 0) + sourceWidth + 1, levelWidth - FLOW_WIDTH),
  );
  const y = Math.max(
    0,
    Math.min(Number(sourceNode.position?.y || 0), levelHeight - FLOW_HEIGHT),
  );
  const flowId = uniqueFlowId(flow.intent, existingNodes);
  const configuredRate = Number(operations?.[flow.operation_id]);
  const defaultRate = Number(flow.default_rate_per_hour || 0);
  const rate = Number.isFinite(configuredRate) && configuredRate > 0 ? configuredRate : defaultRate;
  return {
    error: "",
    node: {
      id: `flow:${flowId}`,
      type: "demandFlow",
      parentId: sourceNode.parentId,
      extent: "parent",
      position: { x, y },
      width: FLOW_WIDTH,
      height: FLOW_HEIGHT,
      style: { width: FLOW_WIDTH, height: FLOW_HEIGHT },
      data: {
        inspector_created: true,
        demand_flow: true,
        flow_id: flowId,
        intent: flow.intent,
        label: flow.label,
        source_element_id: String(sourceNode.id).replace(/^element:/, ""),
        target_element_id: targetNode
          ? String(targetNode.id).replace(/^element:/, "")
          : null,
        operation_id: flow.operation_id,
        rate_per_hour: rate,
      },
      draggable: true,
      selectable: true,
    },
  };
}

export function createSuggestedDemandFlowNode(flow, operations, nodes) {
  const source = nodes.find(
    (node) =>
      String(node.id).startsWith("element:") && node.data?.kind === flow.source_kind,
  );
  if (!source) {
    return {
      node: null,
      error:
        flow.source_kind === "entrance"
          ? "请先放置入口，再添加进站客流。"
          : "请先放置月台，再添加出站或换乘客流。",
    };
  }
  return createDemandFlowNode(flow, source, operations, nodes);
}

function transferTargetFor(sourceNode, nodes) {
  const platforms = nodes.filter(
    (node) => node.id !== sourceNode.id && node.data?.kind === "platform_edge",
  );
  return (
    platforms.find(
      (node) =>
        node.data?.line_id !== sourceNode.data?.line_id ||
        node.data?.direction !== sourceNode.data?.direction,
    ) || platforms[0] || null
  );
}

function uniqueFlowId(intent, nodes) {
  const known = new Set(nodes.map((node) => node.id));
  const stem = `${intent}_${Date.now().toString(36)}`;
  let candidate = stem;
  let index = 2;
  while (known.has(`flow:${candidate}`)) {
    candidate = `${stem}_${index}`;
    index += 1;
  }
  return candidate;
}
