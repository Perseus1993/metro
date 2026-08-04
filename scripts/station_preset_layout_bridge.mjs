import fs from "node:fs";

import { createSuggestedDemandFlowNode } from "../apps/station_designer/src/metro_station_designer/demand_flow_palette.js";
import { createStationSetupNodes } from "../apps/station_designer/src/metro_station_designer/station_setup.js";
import { STATION_SETUP_PRESETS } from "../apps/station_designer/src/metro_station_designer/station_setup_presets.js";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const flowById = new Map(input.passenger_flow_palette.map((flow) => [flow.id, flow]));
const results = STATION_SETUP_PRESETS.map((preset) => buildPreset(preset));
process.stdout.write(JSON.stringify(results));

function buildPreset(preset) {
  const templateId = templateIdForLevels(preset.config.levels);
  const baseNodes = input.base_nodes_by_template[templateId];
  const created = createStationSetupNodes(baseNodes, input.component_palette, preset.config);
  if (created.error) return { preset, template_id: templateId, error: created.error };

  let nodes = created.nodes;
  const flowIds = preset.config.isTransfer
    ? ["entry_flow", "exit_flow", "transfer_flow"]
    : ["entry_flow", "exit_flow"];
  for (const flowId of flowIds) {
    const flow = createSuggestedDemandFlowNode(flowById.get(flowId), input.operations, nodes);
    if (!flow.node) return { preset, template_id: templateId, error: flow.error };
    nodes = [...nodes, flow.node];
  }
  return { preset, template_id: templateId, nodes, counts: created.counts, error: "" };
}

function templateIdForLevels(levels) {
  return {
    1: "scratch_single_level",
    2: "scratch_two_level",
    3: "scratch_three_level",
  }[levels];
}
