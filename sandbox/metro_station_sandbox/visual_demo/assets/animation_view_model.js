(function initMetroAnimationViewModel(root, factory) {
  const api = factory();
  root.MetroAnimationViewModel = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function buildApi() {
  const DEFAULT_LAYOUT = {
    walkable_regions: [],
    connector_channels: [],
    obstacles: [],
    facility_boxes: [],
    decision_regions: [],
    control_points: { platform_doors: [] },
  };

  function buildAnimationViewModel(payload) {
    const raw = isObject(payload) ? payload : null;
    const simulationTrace = objectOrNull(raw?.simulation_trace);
    const visualizationBundle = objectOrNull(raw?.visualization_bundle);
    const visualAnimations = objectOrNull(visualizationBundle?.visual_facility_animations);
    const derived = objectOrNull(raw?.derived);
    const traceScenario = objectOrNull(objectOrNull(simulationTrace?.metadata)?.scenario);
    const duration = positiveNumber(raw?.duration, durationFromTrace(simulationTrace));
    const agents = arrayOr(
      visualizationBundle?.visual_tracks,
      arrayOr(raw?.agents, []),
    );
    const clearanceAudit = objectOr(
      derived?.clearance_audit,
      objectOr(raw?.clearance_audit, clearanceAuditFromTrace(simulationTrace, agents.length)),
    );

    return {
      raw,
      sourceRunId: stringOr(raw?.source_run_id, stringOr(visualizationBundle?.source_run_id, "")),
      schemaVersion: stringOr(raw?.schema_version, ""),
      simulationTrace,
      visualizationBundle,
      derived: derived || {},
      visual: {
        schemaVersion: stringOr(visualizationBundle?.schema_version, ""),
        agents,
        facilityAnimations: visualAnimations || {},
      },
      layout: objectOr(raw?.layout, DEFAULT_LAYOUT),
      scenario: objectOr(raw?.scenario, traceScenario || {}),
      trainService: objectOr(raw?.train_service, {}),
      clearanceAudit,
      duration,
      demoWindowSeconds: positiveNumber(raw?.demo_window_seconds, Math.min(duration || 0, 55)),
      agents,
      queueLayouts: arrayOr(raw?.queue_layouts, []),
      queueSamples: arrayOr(derived?.queue_samples, arrayOr(raw?.queue_samples, [])),
      facilitySamples: arrayOr(derived?.facility_samples, arrayOr(raw?.facility_samples, [])),
      diagnosticSamples: arrayOr(derived?.diagnostic_samples, arrayOr(raw?.diagnostic_samples, [])),
      trainSamples: arrayOr(derived?.train_samples, arrayOr(raw?.train_samples, [])),
      elevatorEvents: arrayOr(
        visualAnimations?.elevator_events,
        arrayOr(raw?.elevator_events, []),
      ),
      conveyorEvents: arrayOr(
        visualAnimations?.conveyor_events,
        arrayOr(raw?.conveyor_events, []),
      ),
      gateEvents: arrayOr(visualAnimations?.gate_events, arrayOr(raw?.gate_events, [])),
      verticalServiceEvents: arrayOr(
        visualAnimations?.vertical_service_events,
        arrayOr(raw?.vertical_service_events, []),
      ),
      facilities: objectOr(raw?.facilities, {}),
    };
  }

  function clearanceAuditFromTrace(trace, fallbackTotal) {
    if (!isObject(trace)) return {};
    const snapshots = arrayOr(trace.snapshots, []);
    const finalSnapshot = objectOr(snapshots[snapshots.length - 1], {});
    const aggregate = objectOr(trace.aggregate_metrics, {});
    const metrics = { ...aggregate, ...objectOr(finalSnapshot.metrics, {}) };
    const spawned = integer(metrics.spawned_persons, fallbackTotal);
    const boarded = integer(metrics.boarded_persons, 0);
    const exited = integer(metrics.exit_gate_served_persons, 0);
    const remaining = integer(metrics.station_persons, arrayOr(finalSnapshot.passengers, []).length);
    const completed = boarded + exited;
    const total = Math.max(spawned, completed + remaining, fallbackTotal);
    return {
      cleared: total <= 0 || remaining <= 0,
      completed_agents: completed,
      remaining_agents: remaining,
      skipped_agents: 0,
      total_agents: total,
      source: "simulation_trace",
    };
  }

  function durationFromTrace(trace) {
    if (!isObject(trace)) return 0;
    const snapshots = arrayOr(trace.snapshots, []);
    const finalSnapshot = objectOr(snapshots[snapshots.length - 1], {});
    return positiveNumber(finalSnapshot.time_seconds, 0);
  }

  function objectOr(value, fallback) {
    return isObject(value) ? value : fallback;
  }

  function objectOrNull(value) {
    return isObject(value) ? value : null;
  }

  function arrayOr(value, fallback) {
    return Array.isArray(value) ? value : fallback;
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function positiveNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  function integer(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.trunc(number) : fallback;
  }

  function stringOr(value, fallback) {
    return typeof value === "string" ? value : fallback;
  }

  return {
    buildAnimationViewModel,
  };
});
