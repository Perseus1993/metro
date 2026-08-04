export const STATION_SETUP_PRESETS = Object.freeze([
  preset(
    "compact_single",
    "单层小型普通站",
    "适合小客流、快速试玩",
    { levels: 1, isTransfer: false, entranceCount: 2, gateCount: 4 },
  ),
  preset(
    "standard_two",
    "二层标准普通站",
    "站厅层 + 月台层的常用结构",
    { levels: 2, isTransfer: false, entranceCount: 3, gateCount: 6 },
  ),
  preset(
    "transfer_two",
    "二层紧凑换乘站",
    "两条线路同层换乘月台",
    { levels: 2, isTransfer: true, entranceCount: 4, gateCount: 8 },
  ),
  preset(
    "transfer_three",
    "三层标准换乘站",
    "站厅、换乘层、月台层",
    { levels: 3, isTransfer: true, entranceCount: 4, gateCount: 8 },
  ),
  preset(
    "hub_three",
    "三层大客流枢纽",
    "最大出入口与闸机配置",
    { levels: 3, isTransfer: true, entranceCount: 6, gateCount: 12 },
  ),
]);

export function stationSetupPreset(presetId) {
  return STATION_SETUP_PRESETS.find((presetItem) => presetItem.id === presetId) || null;
}

function preset(id, label, description, config) {
  return Object.freeze({
    id,
    label,
    description,
    config: Object.freeze({ ...config }),
  });
}
