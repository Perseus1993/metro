(function initMetroSceneRenderModel(root, factory) {
  const api = factory();
  root.MetroSceneRenderModel = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function buildApi() {
  function buildSceneRenderModel(stationScene, assetManifest, canvasWidth, canvasHeight) {
    if (!isObject(stationScene) || stationScene.schema_version !== "station_scene.v1") {
      return null;
    }
    const width = positiveNumber(stationScene?.coordinate_system?.width, 0);
    const height = positiveNumber(stationScene?.coordinate_system?.height, 0);
    if (!width || !height) return null;

    const scale = {
      x: positiveNumber(canvasWidth, 1) / width,
      y: positiveNumber(canvasHeight, 1) / height,
    };
    const diagnostics = [];
    const baseEntities = arrayOr(stationScene.entities, [])
      .map((entity) => normalizeEntity(entity, scale, diagnostics))
      .filter(Boolean);
    const baseEntityById = Object.fromEntries(
      baseEntities.map((entity) => [entity.id, entity]),
    );
    const placementByEntity = validateAssetBindings(
      assetManifest,
      baseEntityById,
      diagnostics,
    );
    const entities = baseEntities.map((entity) => applyAssetPlacement(
      entity,
      placementByEntity.get(entity.id),
      scale,
      diagnostics,
    ));
    const entityById = Object.fromEntries(entities.map((entity) => [entity.id, entity]));
    const runtimeToEntity = {};
    const runtimeBindings = [];
    for (const binding of arrayOr(stationScene.runtime_bindings, [])) {
      const runtimeId = stringOr(binding?.runtime_id, "");
      const entityId = stringOr(binding?.scene_entity_id, "");
      if (!runtimeId || !entityById[entityId]) {
        diagnostics.push({
          code: "runtime_binding_unresolved",
          runtime_id: runtimeId,
          scene_entity_id: entityId,
        });
        continue;
      }
      runtimeToEntity[runtimeId] = entityId;
      const entity = entityById[entityId];
      let position = canvasPoint(binding?.position, scale) || entity.center;
      let exitPosition = canvasPoint(binding?.exit_position, scale) || entity.center;
      if (pointDistance(position, exitPosition) <= 1) {
        const top = [entity.boundsPx.x + entity.boundsPx.w / 2, entity.boundsPx.y];
        const bottom = [
          entity.boundsPx.x + entity.boundsPx.w / 2,
          entity.boundsPx.y + entity.boundsPx.h,
        ];
        const isUp = binding?.direction === "up";
        position = isUp ? bottom : top;
        exitPosition = isUp ? top : bottom;
      }
      runtimeBindings.push({
        runtimeId,
        sceneEntityId: entityId,
        kind: stringOr(binding?.kind, "unknown"),
        stage: stringOr(binding?.stage, ""),
        direction: stringOr(binding?.direction, "both"),
        entryLevelId: binding?.entry_level_id || null,
        exitLevelId: binding?.exit_level_id || null,
        position,
        exitPosition,
      });
    }

    const relations = arrayOr(stationScene.relations, [])
      .map((relation) => normalizeRelation(relation, entityById, diagnostics))
      .filter(Boolean);
    return {
      schemaVersion: stationScene.schema_version,
      sceneId: stringOr(stationScene.scene_id, ""),
      levels: arrayOr(stationScene.levels, []),
      entities: entities.sort(entityDrawOrder),
      entityById,
      relations,
      runtimeToEntity,
      runtimeBindings,
      elevatorEntities: entities.filter((entity) => entity.kind === "elevator"),
      diagnostics,
    };
  }

  function normalizeEntity(entity, scale, diagnostics) {
    const id = stringOr(entity?.entity_id, "");
    const geometry = isObject(entity?.geometry) ? entity.geometry : {};
    const points = geometryPoints(geometry).map(([x, y]) => [x * scale.x, y * scale.y]);
    if (!id || !points.length) {
      diagnostics.push({ code: "entity_geometry_unresolved", scene_entity_id: id });
      return null;
    }
    return entityWithPoints({
      id,
      kind: stringOr(entity?.kind, "unknown"),
      label: stringOr(entity?.label, id),
      levelIds: arrayOr(entity?.level_ids, []).map(String),
      sourceElementId: entity?.source_element_id || null,
      properties: isObject(entity?.properties) ? entity.properties : {},
      metadata: isObject(entity?.metadata) ? entity.metadata : {},
      shape: stringOr(geometry?.shape, "unknown"),
      rotationDeg: finiteNumber(geometry?.rotation_deg, 0),
    }, points);
  }

  function geometryPoints(geometry) {
    if (geometry.shape === "rect") {
      const x = finiteNumber(geometry.x_m, 0);
      const y = finiteNumber(geometry.y_m, 0);
      const width = finiteNumber(geometry.width_m, 0);
      const height = finiteNumber(geometry.height_m, 0);
      const points = [[x, y], [x + width, y], [x + width, y + height], [x, y + height]];
      const rotation = finiteNumber(geometry.rotation_deg, 0);
      return rotation
        ? rotatePoints(points, [x + width / 2, y + height / 2], rotation)
        : points;
    }
    if (geometry.shape === "polygon" || geometry.shape === "polyline") {
      return arrayOr(geometry.points_m, []).map(normalizePoint).filter(Boolean);
    }
    if (geometry.shape === "point") {
      const point = normalizePoint(geometry.position) || geometryPointFromXY(geometry);
      return point ? [point] : [];
    }
    return [];
  }

  function normalizeRelation(relation, entityById, diagnostics) {
    const sourceId = stringOr(relation?.source_entity_id, "");
    const targetId = stringOr(relation?.target_entity_id, "");
    const source = entityById[sourceId];
    const target = entityById[targetId];
    if (!source || !target) {
      diagnostics.push({
        code: "relation_unresolved",
        relation_id: stringOr(relation?.relation_id, ""),
      });
      return null;
    }
    return {
      id: stringOr(relation?.relation_id, ""),
      type: stringOr(relation?.relation_type, "connects"),
      sourceEntityId: sourceId,
      targetEntityId: targetId,
      line: [source.center, target.center],
    };
  }

  function validateAssetBindings(assetManifest, entityById, diagnostics) {
    const placements = new Map();
    if (!isObject(assetManifest)) return placements;
    const assetIds = new Set();
    for (const asset of arrayOr(assetManifest.assets, [])) {
      const assetId = stringOr(asset?.asset_id, "");
      if (!assetId || assetIds.has(assetId)) {
        diagnostics.push({ code: "asset_id_duplicate_or_empty", asset_id: assetId });
        continue;
      }
      assetIds.add(assetId);
    }
    const bindingIds = new Set();
    const boundEntities = new Set();
    for (const binding of arrayOr(assetManifest.bindings, [])) {
      const bindingId = stringOr(binding?.binding_id, "");
      const entityId = stringOr(binding?.scene_entity_id, "");
      const assetId = stringOr(binding?.asset_id, "");
      if (!bindingId || bindingIds.has(bindingId)) {
        diagnostics.push({ code: "asset_binding_id_duplicate_or_empty", binding_id: bindingId });
        continue;
      }
      bindingIds.add(bindingId);
      if (!entityById[entityId] || !assetIds.has(assetId)) {
        diagnostics.push({
          code: "asset_binding_unresolved",
          scene_entity_id: entityId,
          asset_id: assetId,
        });
        continue;
      }
      if (boundEntities.has(entityId)) {
        diagnostics.push({
          code: "asset_binding_duplicate",
          scene_entity_id: entityId,
          binding_id: bindingId,
        });
        continue;
      }
      boundEntities.add(entityId);
      placements.set(entityId, {
        assetId,
        bindingId,
        placement: isObject(binding?.placement) ? binding.placement : {},
      });
    }
    for (const entityId of Object.keys(entityById)) {
      if (!boundEntities.has(entityId)) {
        diagnostics.push({ code: "asset_binding_missing", scene_entity_id: entityId });
      }
    }
    return placements;
  }

  function applyAssetPlacement(entity, binding, scale, diagnostics) {
    if (!binding) return entity;
    const placement = binding.placement;
    const mode = stringOr(placement?.mode, "fit_geometry");
    if (mode !== "fit_geometry") {
      diagnostics.push({
        code: "asset_placement_unsupported",
        scene_entity_id: entity.id,
        mode,
      });
      return { ...entity, assetId: binding.assetId, assetPlacement: placement };
    }
    const parsed = parsePlacementTransform(placement);
    if (!parsed.ok) {
      diagnostics.push({
        code: "asset_placement_invalid",
        scene_entity_id: entity.id,
        field: parsed.field,
      });
      return { ...entity, assetId: binding.assetId, assetPlacement: placement };
    }
    const center = entity.center;
    const angle = parsed.rotationDeg * Math.PI / 180;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const points = entity.points.map(([x, y]) => {
      const localX = (x - center[0]) * parsed.scale[0];
      const localY = (y - center[1]) * parsed.scale[1];
      return [
        center[0] + localX * cos - localY * sin + parsed.offsetM[0] * scale.x,
        center[1] + localX * sin + localY * cos + parsed.offsetM[1] * scale.y,
      ];
    });
    return entityWithPoints({
      ...entity,
      assetId: binding.assetId,
      assetPlacement: placement,
      placementRotationDeg: parsed.rotationDeg,
    }, points);
  }

  function parsePlacementTransform(placement) {
    const offsetM = parsePair(placement?.offset_m, [0, 0], false);
    if (!offsetM) return { ok: false, field: "offset_m" };
    const scale = parsePair(placement?.scale, [1, 1], true);
    if (!scale) return { ok: false, field: "scale" };
    const rotationDeg = placement?.rotation_deg === undefined
      ? 0
      : Number(placement.rotation_deg);
    if (!Number.isFinite(rotationDeg)) return { ok: false, field: "rotation_deg" };
    return { ok: true, offsetM, scale, rotationDeg };
  }

  function parsePair(value, fallback, positive) {
    if (value === undefined) return fallback;
    const raw = typeof value === "number" ? [value, value] : value;
    if (!Array.isArray(raw) || raw.length < 2) return null;
    const result = [Number(raw[0]), Number(raw[1])];
    if (!result.every(Number.isFinite)) return null;
    if (positive && !result.every((item) => item > 0)) return null;
    return result;
  }

  function entityWithPoints(entity, points) {
    const bounds = pointBounds(points);
    return {
      ...entity,
      points,
      center: [(bounds.minX + bounds.maxX) / 2, (bounds.minY + bounds.maxY) / 2],
      boundsPx: {
        x: bounds.minX,
        y: bounds.minY,
        w: Math.max(1, bounds.maxX - bounds.minX),
        h: Math.max(1, bounds.maxY - bounds.minY),
      },
    };
  }

  function rotatePoints(points, center, rotationDeg) {
    const angle = rotationDeg * Math.PI / 180;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    return points.map(([x, y]) => {
      const localX = x - center[0];
      const localY = y - center[1];
      return [
        center[0] + localX * cos - localY * sin,
        center[1] + localX * sin + localY * cos,
      ];
    });
  }

  function geometryPointFromXY(geometry) {
    if (!(Object.prototype.hasOwnProperty.call(geometry, "x_m")
      && Object.prototype.hasOwnProperty.call(geometry, "y_m"))) return null;
    const x = Number(geometry.x_m);
    const y = Number(geometry.y_m);
    return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
  }

  function entityDrawOrder(left, right) {
    const priority = (entity) => {
      if (entity.kind === "walkable_area") return 0;
      if (entity.kind.startsWith("queue:")) return 1;
      if (entity.kind === "platform_edge") return 2;
      return 3;
    };
    return priority(left) - priority(right) || left.id.localeCompare(right.id);
  }

  function pointBounds(points) {
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    return {
      minX: Math.min(...xs),
      minY: Math.min(...ys),
      maxX: Math.max(...xs),
      maxY: Math.max(...ys),
    };
  }

  function pointDistance(left, right) {
    return Math.hypot(right[0] - left[0], right[1] - left[1]);
  }

  function normalizePoint(value) {
    if (!Array.isArray(value) || value.length < 2) return null;
    const x = Number(value[0]);
    const y = Number(value[1]);
    return Number.isFinite(x) && Number.isFinite(y) ? [x, y] : null;
  }

  function canvasPoint(value, scale) {
    const point = normalizePoint(value);
    return point ? [point[0] * scale.x, point[1] * scale.y] : null;
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function arrayOr(value, fallback) {
    return Array.isArray(value) ? value : fallback;
  }

  function stringOr(value, fallback) {
    return typeof value === "string" ? value : fallback;
  }

  function finiteNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function positiveNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  return { buildSceneRenderModel };
});
