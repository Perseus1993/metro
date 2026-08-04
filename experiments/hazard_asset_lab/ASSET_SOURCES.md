# Asset source register

| Category | Candidate | Source | License | Intake status |
|---|---|---|---|---|
| Panic animation | Universal Animation Library 2 (Standard) | https://quaternius.com/packs/universalanimationlibrary2.html | CC0 | Downloaded and imported into the isolated lab. Unity finds 43 unique clips plus the root-motion duplicate set, but no panic/run/flee clip; this package does not satisfy the panic-running requirement by itself. |
| Fire | VFX Particles: Flame Pack | https://assetstore.unity.com/packages/vfx/particles/free-asset-vfx-particles-flame-pack-263899 | Standard Unity Asset Store EULA | Unity received the Asset Store open request, but no package/cache/project files were downloaded. Editor log reports an unavailable access token. Download/import still pending. |
| Robot | Generic Hotel Delivery Robot | Original asset generated inside this isolated lab | Project-owned original; no third-party asset fee | Selected: single enclosed rounded cargo pod, integrated screen face, concealed wheels, emissive status lights |

## Rejected robot candidates

| Candidate | Reason rejected |
|---|---|
| Modern Restaurant Robot Waiter | Paid asset; excluded by the zero-cost requirement. |
| Food Delivery Robot (CGTrader) | Free, but the six-wheel outdoor parcel-box silhouette does not match a hotel delivery robot. |
| ROVIZ hotel/hospital robot (Sketchfab) | Correct category, but approximately 2.3 million triangles and no sufficiently clear download/license evidence for this intake. |
| Service Robot Rig Rigid (Sketchfab) | CC BY-NC; commercial use is prohibited. |

## Robot validation record

- Validated on 2026-08-02 with Unity 6000.3.18f1 batch mode; process returned 0.
- Prefab complexity: 7,744 triangles across built-in primitive meshes.
- Visual check: no magenta/error material in the active render pipeline.
- License/cost: original project-owned geometry and materials; no purchased or downloaded third-party robot content.
- Runtime scope: static prefab and collider only; navigation, animation, and simulation behavior are intentionally not connected.
- Isolation: generated only under `experiments/hazard_asset_lab`; the production metro simulation was not modified.

## Other downloaded intake

| Asset | Local source | Classification | Intake decision |
|---|---|---|---|
| FLAME2020 | `C:/Users/1/Downloads/FLAME2020.zip` | Parametric 3D human face model (`female_model.pkl`, `generic_model.pkl`, `male_model.pkl`); not a fire effect | Keep outside Unity pending a separate digital-human workflow and license review. Do not treat as the fire asset. |

## Acceptance checks

1. Imports in Unity 6000.3.18f1 without compile errors.
2. Materials are generated for the active render pipeline with no magenta shaders; repeat the visual check after enabling an HDRP pipeline asset.
3. Animation clips are discoverable, loop correctly, and have usable root-motion options.
4. Fire/smoke can be bounded and toggled without scene-global dependencies.
5. Robot prefab is brand-free, uses only project-owned geometry/materials, stays under 20k triangles, and reads visually as a hotel/restaurant delivery unit.
6. No dependencies on the production metro simulation project.
