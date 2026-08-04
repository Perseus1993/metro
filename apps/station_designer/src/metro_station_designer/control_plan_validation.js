export const validateControlPlanDraft = (plan, catalog, tickSeconds, horizonSeconds) => {
  const errors = [];
  const warnings = [];
  const definitions = new Map((catalog?.measure_types || []).map((item) => [item.kind, item]));
  for (const measure of plan.measures) {
    validateMeasure(measure, definitions.get(measure.kind), catalog, errors, warnings);
    validateSchedule(measure, plan.events, tickSeconds, horizonSeconds, errors);
  }
  detectTargetConflicts(plan, errors);
  detectGeometryConflicts(plan, warnings);
  return { errors, warnings, valid: errors.length === 0 };
};

const validateMeasure = (measure, definition, catalog, errors, warnings) => {
  if (!definition) {
    errors.push(`${measure.label}：未知管控类型 ${measure.kind}`);
    return;
  }
  if (definition.runtime_status !== "available") {
    errors.push(`${definition.label}：运行语义尚未接入，本轮不能保存为可运行案例`);
  }
  if (!String(measure.label || "").trim()) errors.push(`${definition.label}：名称不能为空`);
  if (definition.placement === "geometry") validateGeometry(measure, errors);
  if (["facility", "escalator"].includes(definition.placement) && !measure.target_id) {
    errors.push(`${measure.label}：请选择目标设施`);
  }
  if (["geometry", "level"].includes(definition.placement) && !measure.level_id) {
    errors.push(`${measure.label}：请选择楼层`);
  }
  if (definition.placement === "escalator") {
    const target = (catalog?.facility_targets || []).find((item) => item.id === measure.target_id);
    if (target && target.kind !== "escalator") errors.push(`${measure.label}：目标必须是扶梯`);
  }
  if (definition.runtime_status !== "available") warnings.push(`${definition.label}仅展示冻结合同`);
};

const validateGeometry = (measure, errors) => {
  const geometry = measure.parameters?.geometry;
  if (!geometry) {
    errors.push(`${measure.label}：缺少作用范围`);
    return;
  }
  for (const key of ["x_m", "y_m", "width_m", "height_m"]) {
    if (!Number.isFinite(Number(geometry[key]))) errors.push(`${measure.label}：${key} 必须是数值`);
  }
  if (Number(geometry.width_m) <= 0 || Number(geometry.height_m) <= 0) {
    errors.push(`${measure.label}：宽高必须大于 0`);
  }
};

const validateSchedule = (measure, events, tickSeconds, horizonSeconds, errors) => {
  const schedule = events
    .filter((event) => event.measure_id === measure.measure_id)
    .sort((left, right) => left.at_seconds - right.at_seconds);
  if (schedule.length !== 2) {
    errors.push(`${measure.label}：必须具有开始和结束事件`);
    return;
  }
  for (const event of schedule) {
    const at = Number(event.at_seconds);
    if (!Number.isInteger(at) || at < 0 || at >= horizonSeconds) {
      errors.push(`${measure.label}：事件时刻必须位于仿真窗口内`);
    } else if (at % tickSeconds !== 0) {
      errors.push(`${measure.label}：事件时刻必须按 ${tickSeconds}s 步长对齐`);
    }
  }
  if (Number(schedule[0].at_seconds) >= Number(schedule[1].at_seconds)) {
    errors.push(`${measure.label}：结束时刻必须晚于开始时刻`);
  }
};

const detectTargetConflicts = (plan, errors) => {
  for (const [index, left] of plan.measures.entries()) {
    if (!left.target_id) continue;
    for (const right of plan.measures.slice(index + 1)) {
      if (left.target_id === right.target_id && overlaps(plan, left, right)) {
        errors.push(`${left.label} 与 ${right.label} 同时控制同一设施`);
      }
    }
  }
};

const detectGeometryConflicts = (plan, warnings) => {
  const geometryMeasures = plan.measures.filter((item) => item.parameters?.geometry);
  for (const [index, left] of geometryMeasures.entries()) {
    for (const right of geometryMeasures.slice(index + 1)) {
      if (left.level_id === right.level_id && overlaps(plan, left, right) && rectanglesOverlap(left, right)) {
        warnings.push(`${left.label} 与 ${right.label} 的作用范围重叠`);
      }
    }
  }
};

const overlaps = (plan, left, right) => {
  const interval = (measure) => plan.events
    .filter((event) => event.measure_id === measure.measure_id)
    .map((event) => Number(event.at_seconds))
    .sort((a, b) => a - b);
  const [leftStart, leftEnd] = interval(left);
  const [rightStart, rightEnd] = interval(right);
  return leftStart < rightEnd && rightStart < leftEnd;
};

const rectanglesOverlap = (left, right) => {
  const a = left.parameters.geometry;
  const b = right.parameters.geometry;
  return Number(a.x_m) < Number(b.x_m) + Number(b.width_m)
    && Number(b.x_m) < Number(a.x_m) + Number(a.width_m)
    && Number(a.y_m) < Number(b.y_m) + Number(b.height_m)
    && Number(b.y_m) < Number(a.y_m) + Number(a.height_m);
};
