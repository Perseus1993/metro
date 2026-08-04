import { fetchJson } from "./api.js?v=debug-log-1";

export const DEFAULT_CONTROLS = {
  seeds: "7,42,99",
  demandMinutes: 1,
  horizonMinutes: 5,
  tickSeconds: 5,
  scenarioMode: "operations",
  initialPlatformPersons: 6,
  alarmDelaySeconds: 0,
};

export const algorithmTemplateControls = () => ({
  ...DEFAULT_CONTROLS,
  scenarioMode: "evacuation",
});

export const caseRequest = (draft, controls, controlPlan) => ({
  ...draft,
  case_name: "Baseline",
  seeds: controls.seeds,
  demand_minutes: Number(controls.demandMinutes),
  horizon_minutes: Number(controls.horizonMinutes),
  tick_seconds: Number(controls.tickSeconds),
  scenario_mode: controls.scenarioMode,
  initial_platform_persons: Number(controls.initialPlatformPersons),
  alarm_delay_seconds: Number(controls.alarmDelaySeconds),
  control_plan: controlPlan,
});

export const controlsFromCase = (analysisCase) => ({
  seeds: (analysisCase.seeds || []).join(","),
  demandMinutes: analysisCase.simulation?.demand_minutes || 1,
  horizonMinutes: analysisCase.simulation?.horizon_minutes || 5,
  tickSeconds: analysisCase.simulation?.tick_seconds || 5,
  scenarioMode: analysisCase.simulation?.scenario_mode || "operations",
  initialPlatformPersons: analysisCase.simulation?.evacuation?.initial_platform_persons || 6,
  alarmDelaySeconds: analysisCase.simulation?.evacuation?.alarm_delay_seconds || 0,
});

export const post = (url, body) => fetchJson(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
