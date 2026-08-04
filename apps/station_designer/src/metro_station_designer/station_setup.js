import { createSuggestedComponentNode } from "./guided_placement.js?v=station-setup-1";

export const STATION_SETUP_LIMITS = Object.freeze({
  levels: { min: 1, max: 3 },
  entrances: { min: 1, max: 6 },
  gates: { min: 2, max: 12 },
});

export function stationSetupTemplateId(levels) {
  const normalized = integerInRange(levels, STATION_SETUP_LIMITS.levels, "楼层数");
  return {
    1: "scratch_single_level",
    2: "scratch_two_level",
    3: "scratch_three_level",
  }[normalized];
}

export function normalizeStationSetup(config) {
  if (!config || typeof config !== "object") {
    throw new Error("建站配置不能为空。");
  }
  if (typeof config.isTransfer !== "boolean") {
    throw new Error("必须选择普通站或换乘站。");
  }
  return {
    levels: integerInRange(config.levels, STATION_SETUP_LIMITS.levels, "楼层数"),
    isTransfer: config.isTransfer,
    entranceCount: integerInRange(
      config.entranceCount,
      STATION_SETUP_LIMITS.entrances,
      "地铁口数量",
    ),
    gateCount: integerInRange(config.gateCount, STATION_SETUP_LIMITS.gates, "闸机数量"),
  };
}

export function stationSetupCounts(config) {
  const normalized = normalizeStationSetup(config);
  return {
    entrances: normalized.entranceCount,
    entryGates: Math.ceil(normalized.gateCount / 2),
    exitGates: Math.floor(normalized.gateCount / 2),
    platforms: normalized.isTransfer ? 2 : 1,
    downEscalators: Math.max(0, normalized.levels - 1),
    upEscalators: Math.max(0, normalized.levels - 1),
    stairs: Math.max(0, normalized.levels - 1),
    elevators: normalized.levels > 1 ? 1 : 0,
  };
}

export function createStationSetupNodes(baseNodes, componentPalette, config) {
  const normalized = normalizeStationSetup(config);
  const counts = stationSetupCounts(normalized);
  const components = new Map(
    (componentPalette || []).map((component) => [component.id, component]),
  );
  let nodes = [...baseNodes];

  for (const [componentId, count, options] of stationSetupSequence(counts, normalized.levels)) {
    const component = components.get(componentId);
    if (!component) {
      return { nodes: baseNodes, config: normalized, counts, error: `缺少设施模板：${componentId}` };
    }
    for (let index = 0; index < count; index += 1) {
      const created = createSuggestedComponentNode(component, nodes, options || {});
      if (!created.node) {
        return { nodes: baseNodes, config: normalized, counts, error: created.error };
      }
      nodes = [...nodes, created.node];
    }
  }

  return { nodes, config: normalized, counts, error: "" };
}

function stationSetupSequence(counts, levels) {
  const sequence = [
    ["entrance", counts.entrances],
    ["entry_gate", counts.entryGates],
    ["exit_gate", counts.exitGates],
    ["platform_edge", 1],
    ["platform_edge_l2_up", counts.platforms - 1],
  ];
  for (let pairIndex = 0; pairIndex < levels - 1; pairIndex += 1) {
    const options = { levelPairIndex: pairIndex };
    sequence.push(
      ["down_escalator", 1, options],
      ["up_escalator", 1, options],
      ["stairs", 1, options],
    );
  }
  sequence.push(["elevator", counts.elevators]);
  return sequence;
}

function integerInRange(value, limits, label) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < limits.min || parsed > limits.max) {
    throw new Error(`${label}必须是 ${limits.min}–${limits.max} 之间的整数。`);
  }
  return parsed;
}
