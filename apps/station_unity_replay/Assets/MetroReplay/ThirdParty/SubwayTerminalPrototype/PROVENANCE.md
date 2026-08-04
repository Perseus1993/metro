# Subway Terminal prototype intake

Status: restricted prototype only. Do not redistribute, sell, or include these files in a commercial/public release until the original creator supplies a verifiable licence.

## Source

- Local archive: `C:\Users\1\Downloads\Subway_Terminal+For+Unity+URP-nextmodel.cn.zip`
- Archive SHA-256: `C462C74997CD21CB10C4A2872217C6B7DC8A867EF5CBFD98C3626B31D11C0093`
- Archive label/source marker: `nextmodel.cn`
- Original project: Unity `2021.3.11f1c2`, URP `12.1.7`
- Intake date: `2026-08-01`

The archive includes a Chinese disclaimer that limits the download to learning/research and non-commercial use, asks users to delete it within 24 hours, and does not identify a verified original licence. A separate user statement that the student creators own copyright has not yet been backed by a signed licence or traceable author identity. The archive notice is therefore treated as the controlling restriction for this prototype intake.

## Imported subset

Only the following raw FBX models and supporting albedo/normal textures were copied. Original prefabs, `.meta` files, URP shaders, demo scenes, `Library`, caches, lightmaps, and project settings were deliberately excluded.

- Escalator start/end modules
- Stair and stair-railing modules
- Information panel and passenger display
- Help point
- Fire extinguisher and cabinet
- Floor, wall, ceiling, escalator, and trim albedo/normal textures

## Unity integration policy

- Imported models are configured with animation, cameras, lights, source materials, and generated colliders disabled.
- Runtime instances live under `B1HeroSample/ImportedStationAssets`.
- All colliders are stripped again at runtime as a defensive check.
- The layer is presentation-only: it must not change Python geometry, facility service, queues, passenger paths, or replay timing.
- Source 2048 px textures are capped to 1024 px for this crowd-scale prototype.
- The source package contains no useful animation clips or LOD chain; custom LOD/performance work remains required.

## Release gate

Before any public or commercial build, either obtain a written licence from the verified creator covering redistribution in an interactive Unity application, or replace every asset listed above with original/clearly licensed equivalents and remove this intake folder.
