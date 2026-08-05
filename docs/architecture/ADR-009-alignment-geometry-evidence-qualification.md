# ADR-009: Keep the Eindhoven Entrance Group as Proxy Geometry

- Status: Accepted
- Date: 2026-08-05
- Scope: Alignment `platform_boarding` release evidence

## Context

Alignment release requires `geometry_evidence_status=observed_matched`. The current scene contains
one single-level rectangular `entrance_a` proxy, while the available Eindhoven sources describe a
multi-level stair/escalator system. The question is whether source evidence is strong enough to
upgrade any part of that entrance group before the mixed 600 evidence campaign.

## Evidence audit

| Source | What it supports | What it does not support |
|---|---|---|
| [Zenodo platform record](https://zenodo.org/records/13784588) | Platform 2 / tracks 3–4 identity; 60 consecutive days; metric trajectory fields; an overhead platform image; acquisition by ProRail | Pixel-to-world control points, an as-built plan, entrance footprint dimensions, vertical topology, or a registration error bound |
| [Pouw et al., stairway study](https://arxiv.org/html/2307.15609) | The actual entrance is the main access to tracks 3–4; a 3.2 m-wide stair, 5.3 m rise, 10.5 m horizontal run, 30° slope, two flights and a 1.5 m landing; 167/290 mm tread geometry; two flanking escalators, directions, 220/400 mm step geometry and 0.6 m/s horizontal velocity | A transform tying those dimensions to the Zenodo platform image or to the current scene coordinate frame; exact entrance origin/rotation relative to platform trajectories |
| [ProRail 2025 project assumptions](https://www.prorail.nl/siteassets/homepage/mini-projectwebsites/ovknoop-ehv/bijlage-3---ske---nota-van-uitgangspunten-versie-3.0_26-juni-2025.pdf) | Future side-platform access is intended to align with existing access; the new passage concept uses two escalators with a fixed stair between | An as-built survey of the current platform-2 entrance; it is a future-design document and cannot certify current dimensions or registration |

The stairway paper is high-quality facility evidence, but it is evidence for a **reference model**,
not evidence that the existing `entrance_a` rectangle is matched. The current scene has no second
level, stair flights, landing, flanking escalators, directional escalator semantics, or sourced
image-to-world transform.

## Decision

Do **not** upgrade the scene, `entrance_a`, or a claimed subset to `observed_matched`.

- Keep the only release status as `geometry_evidence_status=proxy`.
- Classify the documented stair/escalator dimensions as `observed_reference_only`: they may guide
  a replacement geometry, but they do not certify the current rectangle.
- Do not add a third release status such as `partially_observed_matched`. Partial annotations must
  not weaken the existing two-state global gate.
- Mixed 600 may produce Step-5 simulation evidence, but Step 6 and release remain `hold` while this
  ADR's upgrade conditions are unmet.

This is a negative qualification decision, not missing research. It closes the pre-mixed-600
question with an auditable reason.

## Upgrade conditions

All of the following are required before a future ADR may set `observed_matched`:

1. Represent two levels, two stair flights, the 1.5 m landing, and both flanking escalators with
   the observed directions and dimensions.
2. Bind every release-relevant entrance element to a cited source and a content hash.
3. Publish an image/source-to-scene transform from independent control points, with residual/error
   bounds and explicit origin, axes, scale, and rotation.
4. Verify the reconstructed footprint and topology against an as-built drawing or a survey source;
   the 2025 future-design document is insufficient.
5. Add contract tests that reject missing elements, direction reversal, dimension drift, and stale
   evidence fingerprints.

## Consequences

- The permanent hold gate remains honest: strong literature knowledge does not become false scene
  registration evidence.
- The measured dimensions materially reduce the work needed for a replacement entrance model.
- The geometry decision is independent of the frozen holdout and multi-seed convergence gates;
  success in either cannot override this ADR.
