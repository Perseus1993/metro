using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using MetroReplay.Domain;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Presentation
{
    /// <summary>
    /// Free-asset trial layer for the isolated station-fire visual sample.
    /// None of these objects participate in routing, collision, queues or services.
    /// </summary>
    internal sealed class StationElementTrialLayer : IDisposable
    {
        private const string LevelId = "b1_concourse";
        private readonly RuntimeGltfPrototypeLibrary _library = new RuntimeGltfPrototypeLibrary();
        private Transform _root;

        public int InstanceCount { get; private set; }

        public async Task BuildAsync(
            ReplayData data,
            Transform parent,
            string streamingAssetsPath)
        {
            if (data == null)
                throw new ArgumentNullException(nameof(data));
            if (parent == null)
                throw new ArgumentNullException(nameof(parent));

            _root = new GameObject("B1 Station Element Trial Layer · Non-authoritative").transform;
            _root.SetParent(parent, false);
            await LoadFreeAssets(streamingAssetsPath);
            BuildFireAndOperationsSet(data);
            BuildAccessibilityAndCleaningSet(data);
            BuildResponseStaffSet(data);
        }

        public void Dispose()
        {
            _library.Dispose();
            if (_root != null)
                UnityEngine.Object.Destroy(_root.gameObject);
        }

        private async Task LoadFreeAssets(string streamingAssetsPath)
        {
            var decor = Path.Combine(streamingAssetsPath, "Decor");
            var polyHaven = Path.Combine(decor, "PolyHaven");
            await _library.LoadAsync(
                TrialAssetKeys.FireAlarm,
                Path.Combine(polyHaven, "fire_alarm", "fire_alarm_1k.gltf"));
            await _library.LoadAsync(
                TrialAssetKeys.UtilityBox,
                Path.Combine(polyHaven, "utility_box_01", "utility_box_01_1k.gltf"));
            await _library.LoadAsync(
                TrialAssetKeys.Wheelchair,
                Path.Combine(polyHaven, "wheelchair_01", "wheelchair_01_1k.gltf"));
            await _library.LoadAsync(
                TrialAssetKeys.CleanerBottle,
                Path.Combine(polyHaven, "all_purpose_cleaner", "all_purpose_cleaner_1k.gltf"));
            await _library.LoadAsync(
                TrialAssetKeys.Broom,
                Path.Combine(polyHaven, "plastic_broom", "plastic_broom_1k.gltf"));
            await _library.LoadAsync(
                TrialAssetKeys.WallClock,
                Path.Combine(polyHaven, "wall_clock", "wall_clock_1k.gltf"));
        }

        private void BuildFireAndOperationsSet(ReplayData data)
        {
            var floorY = data.GetLevel(LevelId).Elevation + 0.08f;
            var backWall = GameObject.Find("HeroBackWall")?.transform;
            var wallZ = backWall != null
                ? backWall.position.z + 0.22f
                : data.ToWorld(53f, 18.78f, LevelId).z;
            var wallYaw = Quaternion.identity;
            var fireAlarmX = data.ToWorld(48.7f, 18.78f, LevelId).x;
            var utilityBoxX = data.ToWorld(50.8f, 18.45f, LevelId).x;
            var wallClockX = data.ToWorld(46.5f, 18.78f, LevelId).x;
            Place(
                TrialAssetKeys.FireAlarm,
                "Manual fire alarm call point",
                new Vector3(fireAlarmX, floorY + 1.30f, wallZ + 0.03f),
                wallYaw,
                0.24f,
                "Poly Haven");
            Place(
                TrialAssetKeys.UtilityBox,
                "Electrical distribution cabinet",
                new Vector3(utilityBoxX, floorY, wallZ + 0.18f),
                wallYaw,
                1.28f,
                "Poly Haven");
            Place(
                TrialAssetKeys.WallClock,
                "Station wall clock",
                new Vector3(wallClockX, floorY + 1.88f, wallZ + 0.03f),
                wallYaw,
                0.42f,
                "Poly Haven");
        }

        private void BuildAccessibilityAndCleaningSet(ReplayData data)
        {
            Place(
                TrialAssetKeys.Wheelchair,
                "Wheelchair mobility aid",
                data.ToWorld(37.8f, 10.2f, LevelId, 0.08f),
                Quaternion.Euler(0f, 28f, 0f),
                1.12f,
                "Poly Haven");

            var cartPosition = data.ToWorld(58.7f, 9.25f, LevelId, 0.08f);
            Place(
                TrialAssetKeys.CleanerBottle,
                "Cleaning supplies bottle",
                cartPosition + new Vector3(0.34f, 0f, 0.04f),
                Quaternion.Euler(0f, -24f, 0f),
                0.28f,
                "Poly Haven");
            Place(
                TrialAssetKeys.Broom,
                "Station cleaning broom",
                cartPosition + new Vector3(-0.32f, 0f, -0.24f),
                Quaternion.Euler(0f, -28f, -7f),
                1.22f,
                "Poly Haven");
        }

        private void BuildResponseStaffSet(ReplayData data)
        {
            var library = RocketboxPassengerLibrary.Load();
            var prototypes = library.OperationsPrototypes;
            var placements = new[]
            {
                new StaffPlacement("Fire_", "Fire response staff", 48.4f, 10.55f),
                new StaffPlacement("Medical_", "Medical response staff", 50.0f, 10.25f),
                new StaffPlacement("Police_", "Police response staff", 51.6f, 9.95f),
                new StaffPlacement("Construction_", "Maintenance staff", 53.2f, 9.65f)
            };
            var target = data.ToWorld(44.7f, 13.5f, LevelId, 1f);
            var floorY = data.GetLevel(LevelId).Elevation + 0.08f;

            foreach (var placement in placements)
            {
                var prototype = prototypes.FirstOrDefault(item =>
                    item.name.StartsWith(placement.Prefix, StringComparison.Ordinal));
                if (prototype == null)
                    continue;
                var position = data.ToWorld(placement.X, placement.Z, LevelId, 0.08f);
                var direction = target - position;
                direction.y = 0f;
                var instance = UnityEngine.Object.Instantiate(
                    prototype,
                    position,
                    direction.sqrMagnitude > 0.001f
                        ? Quaternion.LookRotation(direction.normalized)
                        : Quaternion.identity,
                    _root);
                instance.name = placement.Label + " · Visual only";
                RemovePhysicalComponents(instance);
                RemoveSubmeshesWithTokens(instance, "pistol", "gun", "rifle");
                Ground(instance, floorY);
                var identity = instance.GetComponent<VisualOnlyStationAssetIdentity>()
                               ?? instance.AddComponent<VisualOnlyStationAssetIdentity>();
                identity.Configure(placement.Label, "Microsoft Rocketbox", "MIT");
                var animator = instance.GetComponent<Animator>();
                if (animator != null && animator.runtimeAnimatorController != null)
                    animator.Play("Idle_Loop", 0, InstanceCount * 0.17f % 1f);
                InstanceCount++;
            }
        }

        private void Place(
            string key,
            string assetId,
            Vector3 position,
            Quaternion rotation,
            float height,
            string source)
        {
            var instance = _library.Create(key, _root);
            instance.name = assetId + " · Visual only";
            instance.transform.SetPositionAndRotation(position, rotation);
            instance.transform.localScale = Vector3.one * height;
            RemovePhysicalComponents(instance);
            var identity = instance.AddComponent<VisualOnlyStationAssetIdentity>();
            identity.Configure(assetId, source, "CC0-1.0");
            InstanceCount++;
        }

        private static void Ground(GameObject instance, float floorY)
        {
            var renderers = instance.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
                return;
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++)
                bounds.Encapsulate(renderers[index].bounds);
            instance.transform.position += Vector3.up * (floorY - bounds.min.y);
        }

        private static void RemovePhysicalComponents(GameObject instance)
        {
            foreach (var collider in instance.GetComponentsInChildren<Collider>(true))
                DestroyObject(collider);
            foreach (var body in instance.GetComponentsInChildren<Rigidbody>(true))
                DestroyObject(body);
        }

        private static void RemoveSubmeshesWithTokens(GameObject instance, params string[] tokens)
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
                    var materialName = materials[index]?.name ?? string.Empty;
                    if (!tokens.Any(token =>
                            materialName.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0))
                        continue;
                    if (workingMesh == null)
                    {
                        workingMesh = UnityEngine.Object.Instantiate(sourceMesh);
                        workingMesh.name = sourceMesh.name + "_StationSafeVisual";
                    }
                    workingMesh.SetTriangles(Array.Empty<int>(), index, false);
                }
                if (workingMesh == null)
                    continue;
                workingMesh.RecalculateBounds();
                renderer.sharedMesh = workingMesh;
                renderer.shadowCastingMode = ShadowCastingMode.On;
            }
        }

        private static void DestroyObject(UnityEngine.Object target)
        {
            if (UnityEngine.Application.isPlaying)
                UnityEngine.Object.Destroy(target);
            else
                UnityEngine.Object.DestroyImmediate(target);
        }

        private readonly struct StaffPlacement
        {
            public string Prefix { get; }
            public string Label { get; }
            public float X { get; }
            public float Z { get; }

            public StaffPlacement(string prefix, string label, float x, float z)
            {
                Prefix = prefix;
                Label = label;
                X = x;
                Z = z;
            }
        }

        private static class TrialAssetKeys
        {
            public const string FireAlarm = "trial_fire_alarm";
            public const string UtilityBox = "trial_utility_box";
            public const string Wheelchair = "trial_wheelchair";
            public const string CleanerBottle = "trial_cleaner_bottle";
            public const string Broom = "trial_cleaning_broom";
            public const string WallClock = "trial_wall_clock";
        }
    }
}
