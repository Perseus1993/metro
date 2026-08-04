import { useCallback, useMemo, useState } from "react";

import {
  appendControlMeasure,
  controlPlanFromCase,
  createEmptyControlPlan,
  removeControlMeasure,
  reviseControlEvent,
  reviseControlGeometry,
  reviseControlMeasure,
} from "./control_plan_draft.js?v=control-plan-1";
import { validateControlPlanDraft } from "./control_plan_validation.js?v=control-plan-1";

export const useControlPlanEditor = (catalog, controls) => {
  const [plan, setPlan] = useState(createEmptyControlPlan);
  const tickSeconds = Math.max(1, Number(controls.tickSeconds) || 1);
  const horizonSeconds = Math.max(tickSeconds * 2, Number(controls.horizonMinutes) * 60 || 120);
  const validation = useMemo(
    () => validateControlPlanDraft(plan, catalog, tickSeconds, horizonSeconds),
    [catalog, horizonSeconds, plan, tickSeconds],
  );
  const addMeasure = useCallback((kind) => {
    const definition = catalog?.measure_types?.find((item) => item.kind === kind);
    if (!definition || definition.runtime_status !== "available") return;
    setPlan((current) => appendControlMeasure(
      current, definition, catalog, tickSeconds, horizonSeconds,
    ));
  }, [catalog, horizonSeconds, tickSeconds]);
  const loadFromCase = useCallback((analysisCase) => setPlan(controlPlanFromCase(analysisCase)), []);

  return {
    addMeasure,
    catalog,
    horizonSeconds,
    loadFromCase,
    plan,
    removeMeasure: (measureId) => setPlan((current) => removeControlMeasure(current, measureId)),
    reviseEvent: (eventId, changes) => setPlan((current) => reviseControlEvent(current, eventId, changes)),
    reviseGeometry: (measureId, changes) => setPlan((current) => reviseControlGeometry(current, measureId, changes)),
    reviseMeasure: (measureId, changes) => setPlan((current) => reviseControlMeasure(current, measureId, changes)),
    serializedPlan: plan.measures.length ? plan : null,
    tickSeconds,
    validation,
  };
};
