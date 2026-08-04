export function updateDemandFlowRate(nodes, nodeId, rawValue) {
  const value = finiteNonNegative(rawValue);
  return nodes.map((node) =>
    node.id === nodeId && node.data?.demand_flow
      ? { ...node, data: { ...node.data, rate_per_hour: value } }
      : node,
  );
}

export function updateDemandFlowTarget(nodes, nodeId, targetElementId) {
  return nodes.map((node) =>
    node.id === nodeId && node.data?.demand_flow && node.data?.intent === "transfer"
      ? { ...node, data: { ...node.data, target_element_id: targetElementId || null } }
      : node,
  );
}

export function updateDemandFlowTotal(nodes, operationId, rawTotal) {
  const total = finiteNonNegative(rawTotal);
  const matching = nodes.filter(
    (node) => node.data?.demand_flow && node.data?.operation_id === operationId,
  );
  if (!matching.length) {
    return nodes;
  }
  const currentTotal = matching.reduce(
    (sum, node) => sum + finiteNonNegative(node.data?.rate_per_hour),
    0,
  );
  const equalShare = total / matching.length;
  return nodes.map((node) => {
    if (!matching.includes(node)) {
      return node;
    }
    const current = finiteNonNegative(node.data?.rate_per_hour);
    const rate = currentTotal > 0 ? (current / currentTotal) * total : equalShare;
    return { ...node, data: { ...node.data, rate_per_hour: Math.round(rate) } };
  });
}

function finiteNonNegative(rawValue) {
  const value = Number(rawValue);
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}
