using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Presentation
{
    internal static class StationFireOperationsVisuals
    {
        private const string LevelId = "b1_concourse";
        private const string BarrierResourceRoot = "StationOperations/Prefabs/";

        public static Transform Build(ReplayData data, Transform parent)
        {
            var root = new GameObject("B1 Station Operations Visuals · Non-authoritative").transform;
            root.SetParent(parent, false);
            BuildWaterBarrierCordon(data, root);
            BuildSecurityStaff(data, root);
            return root;
        }

        private static void BuildWaterBarrierCordon(ReplayData data, Transform parent)
        {
            var red = Resources.Load<GameObject>(BarrierResourceRoot + "WaterBarrier_Red");
            var yellow = Resources.Load<GameObject>(BarrierResourceRoot + "WaterBarrier_Yellow");
            if (red == null || yellow == null)
            {
                Debug.LogWarning(
                    "CC0 water-barrier prefabs are unavailable; run Hazard Visual Lab/Build Station Safety Assets.");
                return;
            }

            var root = new GameObject("Temporary Water Barrier Cordon · Visual only").transform;
            root.SetParent(parent, false);
            var placements = new[]
            {
                new BarrierPlacement(red, 40.5f, 9.4f, 8f),
                new BarrierPlacement(yellow, 42.7f, 9.4f, 8f),
                new BarrierPlacement(red, 46.4f, 9.4f, 8f),
                new BarrierPlacement(yellow, 48.6f, 9.4f, 8f)
            };
            foreach (var placement in placements)
            {
                var position = data.ToWorld(placement.X, placement.Z, LevelId, 0.08f);
                PlaceScaled(
                    placement.Prefab,
                    root,
                    position,
                    Quaternion.Euler(0f, placement.Yaw, 0f),
                    new Vector3(1.72f, 0.92f, 0.48f));
            }
        }

        private static void BuildSecurityStaff(ReplayData data, Transform parent)
        {
            var library = RocketboxPassengerLibrary.Load();
            if (library.SecurityBaseCount == 0)
            {
                Debug.LogWarning("Rocketbox security staff prefabs are unavailable.");
                return;
            }

            var checkpoint = GameObject.Find("SecurityCheckpoint")?.transform;
            var scanner = checkpoint != null ? checkpoint.Find("XRayScannerBody") : null;
            if (scanner == null)
            {
                Debug.LogWarning("B1 security checkpoint anchor is unavailable; visual staff were not placed.");
                return;
            }

            var root = new GameObject("Security Staff · Visual only").transform;
            root.SetParent(parent, false);
            var floorY = data.GetLevel(LevelId).Elevation + 0.08f;
            var prototypes = new List<GameObject>(library.SecurityPrototypes);
            prototypes.Sort((left, right) => string.Compare(left.name, right.name, StringComparison.Ordinal));
            var positions = new[]
            {
                new Vector3(scanner.position.x - 2.55f, floorY, scanner.position.z - 0.58f),
                new Vector3(scanner.position.x + 4.35f, floorY, scanner.position.z - 0.48f)
            };

            for (var index = 0; index < prototypes.Count && index < positions.Length; index++)
            {
                var instance = UnityEngine.Object.Instantiate(
                    prototypes[index],
                    positions[index],
                    Quaternion.LookRotation(Vector3.forward),
                    root);
                instance.name = prototypes[index].name + " · Station security · Visual only";
                RemovePhysicalComponents(instance);
                if (instance.name.StartsWith("Security_Female_", StringComparison.Ordinal))
                    RemoveSubmeshesWithMaterialToken(instance, "pistol");
                Ground(instance, floorY);
                var identity = instance.GetComponent<VisualOnlyStationAssetIdentity>()
                               ?? instance.AddComponent<VisualOnlyStationAssetIdentity>();
                identity.Configure(instance.name, "Microsoft Rocketbox", "MIT");
                var animator = instance.GetComponent<Animator>();
                if (animator != null && animator.runtimeAnimatorController != null)
                {
                    animator.speed = 0.72f + index * 0.08f;
                    animator.Play("Idle_Loop", 0, index * 0.31f);
                }
            }
        }

        private static void PlaceScaled(
            GameObject prototype,
            Transform parent,
            Vector3 basePosition,
            Quaternion rotation,
            Vector3 targetSize)
        {
            var instance = UnityEngine.Object.Instantiate(prototype, parent, false);
            instance.name = prototype.name + " · Water barrier · Visual only";
            instance.transform.SetPositionAndRotation(Vector3.zero, rotation);
            instance.transform.localScale = Vector3.one;
            RemovePhysicalComponents(instance);
            SetStatic(instance, false);
            if (!TryGetBounds(instance, out var bounds))
            {
                UnityEngine.Object.Destroy(instance);
                return;
            }

            instance.transform.localScale = new Vector3(
                targetSize.x / Mathf.Max(0.001f, bounds.size.x),
                targetSize.y / Mathf.Max(0.001f, bounds.size.y),
                targetSize.z / Mathf.Max(0.001f, bounds.size.z));
            TryGetBounds(instance, out bounds);
            instance.transform.position += basePosition
                                           - new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);
        }

        private static void Ground(GameObject instance, float floorY)
        {
            if (!TryGetBounds(instance, out var bounds))
                return;
            instance.transform.position += Vector3.up * (floorY - bounds.min.y);
        }

        private static bool TryGetBounds(GameObject instance, out Bounds bounds)
        {
            bounds = default;
            var found = false;
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                if (!renderer.enabled)
                    continue;
                if (!found)
                {
                    bounds = renderer.bounds;
                    found = true;
                }
                else
                {
                    bounds.Encapsulate(renderer.bounds);
                }
            }
            return found;
        }

        private static void RemoveSubmeshesWithMaterialToken(GameObject instance, string token)
        {
            foreach (var renderer in instance.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                var sourceMesh = renderer.sharedMesh;
                if (sourceMesh == null)
                    continue;
                Mesh workingMesh = null;
                var materials = renderer.sharedMaterials;
                for (var index = 0; index < materials.Length && index < sourceMesh.subMeshCount; index++)
                {
                    var material = materials[index];
                    if (material == null
                        || material.name.IndexOf(token, StringComparison.OrdinalIgnoreCase) < 0)
                        continue;
                    if (workingMesh == null)
                    {
                        workingMesh = UnityEngine.Object.Instantiate(sourceMesh);
                        workingMesh.name = sourceMesh.name + "_StationSafeVisual";
                    }
                    workingMesh.SetTriangles(Array.Empty<int>(), index, false);
                }
                if (workingMesh != null)
                {
                    workingMesh.RecalculateBounds();
                    renderer.sharedMesh = workingMesh;
                    renderer.shadowCastingMode = ShadowCastingMode.On;
                }
            }
        }

        private static void RemovePhysicalComponents(GameObject instance)
        {
            foreach (var collider in instance.GetComponentsInChildren<Collider>(true))
                DestroyObject(collider);
            foreach (var body in instance.GetComponentsInChildren<Rigidbody>(true))
                DestroyObject(body);
        }

        private static void SetStatic(GameObject instance, bool value)
        {
            foreach (var child in instance.GetComponentsInChildren<Transform>(true))
                child.gameObject.isStatic = value;
        }

        private static void DestroyObject(UnityEngine.Object target)
        {
            if (UnityEngine.Application.isPlaying)
                UnityEngine.Object.Destroy(target);
            else
                UnityEngine.Object.DestroyImmediate(target);
        }

        private readonly struct BarrierPlacement
        {
            public GameObject Prefab { get; }
            public float X { get; }
            public float Z { get; }
            public float Yaw { get; }

            public BarrierPlacement(GameObject prefab, float x, float z, float yaw)
            {
                Prefab = prefab;
                X = x;
                Z = z;
                Yaw = yaw;
            }
        }
    }
}
