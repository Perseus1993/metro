# Hazard Asset Lab

Independent Unity 6.3 / HDRP 17.3 asset-evaluation project for metro fire,
panic-animation, and service-robot candidates.

## Isolation contract

- Do not reference or copy assets from `apps/station_unity_replay`.
- Do not connect this project to replay JSON, simulation state, or production code.
- Keep all third-party downloads under `AssetStoreDownloads/` until their license
  and Unity import behavior have been checked.
- Only promote an asset after visual, shader, animation, and performance checks.

## Planned test scene

`Assets/HazardAssetLab/Scenes/HazardAssetGallery.unity`

The gallery will contain three independent bays: panic locomotion, fire/smoke,
and service robot. It is an asset viewer, not a simulation scene.

## Free hotel delivery robot

The lab contains an original, brand-free Unity prefab generated from built-in
geometry and pipeline-adaptive materials. It does not depend on a purchased or
downloaded third-party robot model.

The selected shape is a single enclosed rounded cargo pod. Exposed restaurant
trays are intentionally excluded.

- Prefab: `Assets/HazardAssetLab/Prefabs/GenericHotelDeliveryRobot.prefab`
- Preview scene: `Assets/HazardAssetLab/Scenes/RobotAssetPreview.unity`
- Preview image: `Assets/HazardAssetLab/Previews/GenericHotelDeliveryRobot.png`
- Regenerator: `Hazard Asset Lab > Generate Free Hotel Delivery Robot`
