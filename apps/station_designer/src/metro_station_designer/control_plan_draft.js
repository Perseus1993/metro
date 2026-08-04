const SCHEMA_VERSION = "control-plan/v1";

export const createEmptyControlPlan = () => {
  const timestamp = new Date().toISOString();
  return {
    schema_version: SCHEMA_VERSION,
    plan_id: identifier("control-plan"),
    name: "管控时间轴",
    created_at: timestamp,
    updated_at: timestamp,
    measures: [],
    events: [],
    metadata: { source: "station_designer" },
  };
};

export const appendControlMeasure = (plan, definition, catalog, tickSeconds, horizonSeconds) => {
  const measureId = identifier(definition.kind);
  const placement = placementDefaults(definition, catalog);
  const endSeconds = Math.max(
    tickSeconds,
    Math.min(tickSeconds * 3, Math.max(tickSeconds, horizonSeconds - tickSeconds)),
  );
  const measure = {
    measure_id: measureId,
    kind: definition.kind,
    label: `${definition.label} ${plan.measures.length + 1}`,
    target_id: placement.targetId,
    level_id: placement.levelId,
    initially_active: false,
    parameters: placement.parameters,
    metadata: { source: "station_designer" },
  };
  const startParameters = definition.directions?.length
    ? { direction: definition.directions[0] }
    : {};
  const events = [
    eventFor(measureId, "start", 0, definition.start_action, startParameters),
    eventFor(measureId, "end", endSeconds, definition.end_action, {}),
  ];
  return touch({
    ...plan,
    measures: [...plan.measures, measure],
    events: [...plan.events, ...events],
  });
};

export const removeControlMeasure = (plan, measureId) => touch({
  ...plan,
  measures: plan.measures.filter((measure) => measure.measure_id !== measureId),
  events: plan.events.filter((event) => event.measure_id !== measureId),
});

export const reviseControlMeasure = (plan, measureId, changes) => touch({
  ...plan,
  measures: plan.measures.map((measure) =>
    measure.measure_id === measureId ? { ...measure, ...changes } : measure),
});

export const reviseControlGeometry = (plan, measureId, changes) => {
  const measure = plan.measures.find((item) => item.measure_id === measureId);
  if (!measure) return plan;
  return reviseControlMeasure(plan, measureId, {
    parameters: {
      ...measure.parameters,
      geometry: { ...measure.parameters.geometry, ...changes },
    },
  });
};

export const reviseControlEvent = (plan, eventId, changes) => touch({
  ...plan,
  events: plan.events
    .map((event) => event.event_id === eventId ? { ...event, ...changes } : event)
    .sort((left, right) => left.at_seconds - right.at_seconds || left.event_id.localeCompare(right.event_id)),
});

export const controlPlanFromCase = (analysisCase) => {
  const source = analysisCase?.simulation?.control_plan;
  if (!source) return createEmptyControlPlan();
  const { semantic_fingerprint: _fingerprint, ...plan } = source;
  return {
    ...plan,
    measures: (plan.measures || []).map((measure) => ({ ...measure })),
    events: (plan.events || []).map((event) => ({ ...event })),
  };
};

const placementDefaults = (definition, catalog) => {
  const level = catalog?.levels?.[0] || {};
  const targets = (catalog?.facility_targets || []).filter((target) =>
    definition.placement !== "escalator" || target.kind === "escalator");
  const target = targets[0] || {};
  const geometry = level.default_geometry || {
    shape: "rect", x_m: 4, y_m: 4, width_m: 2, height_m: 1,
    rotation_deg: 0, points_m: [],
  };
  return {
    targetId: ["facility", "escalator"].includes(definition.placement) ? target.id || null : null,
    levelId: ["geometry", "level"].includes(definition.placement)
      ? level.id || null
      : target.level_id || null,
    parameters: definition.placement === "geometry" ? { geometry: { ...geometry } } : {},
  };
};

const eventFor = (measureId, suffix, atSeconds, action, parameters) => ({
  event_id: `${measureId}-${suffix}`,
  measure_id: measureId,
  at_seconds: atSeconds,
  action,
  parameters,
  metadata: { source: "station_designer" },
});

const touch = (plan) => ({ ...plan, updated_at: new Date().toISOString() });

const identifier = (prefix) => {
  const unique = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${unique}`.replace(/[^a-zA-Z0-9_-]/g, "");
};
