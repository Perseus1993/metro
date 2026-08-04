# ADR-008: Separate Replay Scene Topology from Runtime Traces and Assets

- Status: Accepted
- Date: 2026-07-16
- Amended: 2026-07-18

## Context

The design compiler can produce multiple physical facilities, including multiple elevators, but
the legacy replay renderer still receives a fixed demo layout and a single elevator payload.
Runtime facilities also have a finer granularity than physical assets: one physical elevator can
compile into separate upward and downward service processes. Inferring this relationship from
string IDs inside the renderer is brittle.

The replay boundary must therefore preserve three different concerns:

1. the physical station scene and its topology;
2. the time-varying simulation trace and runtime facility identities;
3. presentation assets and their placement on physical scene entities.

## Decision

Publish the following versioned contracts:

- `station_scene.v1` contains levels, physical entities, semantic relations, compiled graph
  topology, and explicit runtime-facility-to-scene-entity bindings;
- `asset_manifest.v1` contains reusable asset descriptors and per-entity placement bindings;
- `replay_package.v2` composes the scene and asset manifest, and references the sibling
  `simulation_trace` and `visualization_bundle` through local JSON pointers.

Every runtime `FacilitySpec` compiled from a design element records `source_element_id`. A
renderer must use the explicit binding and must not reconstruct ownership by parsing runtime IDs.
One physical facility may own any number of runtime facilities.

Assets remain presentation-only. The initial implementation binds semantic entity kinds to
procedural placeholders. Binary GLB, texture, LOD, and animation-channel resolution can be added
behind the asset manifest without changing simulation truth.

The PM-028 E5 audit closes the ambiguous part of that statement as follows:

- `asset_manifest.v1` is the stable procedural-asset contract. Its renderer supports
  `fit_geometry` plus finite positive `scale`, finite `rotation_deg`, and finite `offset_m`.
  Invalid or unsupported placement is diagnosed and falls back to the unmodified scene geometry;
- scene `rect.rotation_deg` is geometry truth and is applied before presentation placement;
- `asset_manifest.v1` does **not** load or validate external binary content. A descriptor that is
  not understood by the 2D renderer remains a procedural semantic fallback and must not be
  presented as a successfully imported GLB;
- external content URI/hash, metre/unit conversion, up/front axes, origin/anchor, LOD, animation
  channels, material/texture colour space, licence and failure budgets require a new
  `asset_manifest.v2` proposal. They will not be smuggled into unconstrained v1 metadata.

The existing top-level `visualization_bundle.v1` envelope and legacy layout fields remain during
the migration. New consumers read `replay_package`; old consumers continue to function until the
generic renderer replaces fixed layout constants.

## Invariants

- Every runtime facility in a replay package maps to exactly one scene entity.
- Multiple runtime facilities may map to the same physical scene entity.
- Scene and asset references use stable IDs and reject duplicates or unknown references.
- Serialized scene, asset, and replay packages carry semantic fingerprints.
- Assets never alter routing, capacity, service behavior, or simulation metrics.
- Unsupported asset kinds fall back to a procedural representation instead of disappearing.

## Delivery Slices

1. **Implemented:** contracts, scene compiler, explicit source-element ownership, procedural asset
   bindings, consumer view-model exposure, and a three-elevator golden test.
2. **Implemented:** the 2D renderer iterates scene entities and relations, places geometry from the
   scene coordinate system, validates asset/runtime references, and renders each physical elevator
   with only the rides mapped to that entity.
3. **Implemented:** `LayoutRecipe v1` and `ScenarioCorpus v1` generate deterministic one-, two-,
   and three-level stations with controlled entrance, gate, elevator, stair, escalator, mirror, and
   asset-density variations. Static acceptance recompiles every design into `StationScene v1`,
   checks all runtime and asset references, and samples generated designs through the existing
   journey and operational simulation gates. A three-level six-elevator scene is compiled through
   the JavaScript render model without hard-coded facility counts.
4. **Implemented:** scene diagnostics are visible in the UI; level buttons filter same-level and
   cross-level entities; rect rotation and bounded v1 placement overrides are applied; 12 scenes
   across three desktop viewports pass real-Chromium structure and error checks.
5. **Next (PM-029):** specify and review `asset_manifest.v2`, then implement external asset
   catalogue/import validation, content hashes, coordinate normalization, LOD and animation
   channels. No external binary asset is accepted as integrated before that decision.
6. **Later:** optional 3D rendering after the topology-correct 2D path is accepted.

## Consequences

- Upstream station generation can add facilities without requiring per-facility renderer code.
- Physical asset reuse and runtime process multiplicity are represented independently.
- Replay files grow because they carry a static scene snapshot, but remain self-describing and
  reproducible.
- Replay packages use the generic scene path; legacy payloads without `replay_package` retain the
  fixed demo renderer as a compatibility fallback.
- Large generated corpora live in quality tooling rather than the production domain. Successful
  cases are reproduced from versioned recipes; only minimized failures need durable design files.
