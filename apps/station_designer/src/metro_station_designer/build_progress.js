export function stationBuildProgress(nodes, payload, stationGenerated) {
  const elements = nodes.filter((node) => String(node.id).startsWith("element:"));
  const levels = nodes
    .filter((node) => node.type === "levelGroup")
    .sort((left, right) => Number(left.position?.y || 0) - Number(right.position?.y || 0));
  const hasEntrance = elements.some((node) => node.data?.kind === "entrance");
  const hasEntryGate = elements.some(
    (node) =>
      node.data?.kind === "gate" &&
      ["entry", "bidirectional"].includes(node.data?.gate_direction),
  );
  const hasExitGate = elements.some(
    (node) =>
      node.data?.kind === "gate" &&
      ["exit", "bidirectional"].includes(node.data?.gate_direction),
  );
  const hasPlatform = elements.some((node) => node.data?.kind === "platform_edge");
  const verticalReady = levels.length <= 1 || adjacentLevelsConnected(levels, elements);
  const demandReady = nodes.some((node) => node.data?.demand_flow);
  const compileReady = stationGenerated && payload?.summary?.status !== "error";
  const items = [
    item("entrance", "入口", hasEntrance),
    item("entry_gate", "进站闸机", hasEntryGate),
    item("exit_gate", "出站闸机", hasExitGate),
    item("platform", "月台", hasPlatform),
    ...(levels.length > 1 ? [item("vertical", "跨层通道", verticalReady)] : []),
    item("generated", "生成站点", stationGenerated),
    item("demand", "定义客流", demandReady),
    item("ready", "可以仿真", compileReady && demandReady),
  ];
  return {
    isScratch: Boolean(payload?.document?.metadata?.editor_scratch),
    items,
    next: nextInstruction(items, levels.length),
  };
}

function adjacentLevelsConnected(levels, elements) {
  const connectors = elements.filter((node) => node.data?.role === "vertical_connector");
  return levels.slice(0, -1).every((level, index) => {
    const nextLevel = levels[index + 1];
    const upperId = level.data?.level_id;
    const lowerId = nextLevel.data?.level_id;
    const pairConnectors = connectors.filter((node) => {
      const connected = new Set(node.data?.connects_levels || []);
      return connected.has(upperId) && connected.has(lowerId);
    });
    const hasDown = pairConnectors.some(
      (node) => ["down", "both"].includes(node.data?.direction),
    );
    const hasUp = pairConnectors.some(
      (node) => ["up", "both"].includes(node.data?.direction),
    );
    return hasDown && hasUp;
  });
}

function item(id, label, complete) {
  return { id, label, complete: Boolean(complete) };
}

function nextInstruction(items, levelCount) {
  const missing = items.find((candidate) => !candidate.complete);
  const instructions = {
    entrance: "点一下左侧“入口”，系统会放到站厅层；也可以拖进去。",
    entry_gate: "继续点“进站闸机”。",
    exit_gate: "继续点“出站闸机”。",
    platform: "点“月台”，系统会自动放到底层。",
    vertical:
      levelCount > 2
        ? "每个楼层段都要能上下通行：点楼梯，或成对放置上下行扶梯；直梯可一次连接全部楼层。"
        : "上下都要可通行：点楼梯/直梯，或分别放置上下行扶梯。",
    generated: "设施齐了，点击顶部绿色“2 生成站点”。",
    demand: "点左侧客流卡片：进站绑定入口，出站/换乘绑定月台。",
    ready: "查看右侧诊断；全部通过后即可开始仿真。",
  };
  return {
    id: missing?.id || "done",
    title: missing ? `下一步：${missing.label}` : "站点已可仿真",
    instruction: missing ? instructions[missing.id] : "点击右侧“4 开始仿真”。",
  };
}
