using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Presentation
{
    internal static class B1HeroImportedAssetBuilder
    {
        private const string ModelRoot =
            "MetroReplay/ThirdParty/SubwayTerminalPrototype/Models/";

        public static void Build(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("ImportedStationAssets").transform;
            root.SetParent(parent, false);

            BuildVerticalTransport(root, center, floorY, materials);
            BuildServiceProps(root, center, floorY, materials);
        }

        private static void BuildVerticalTransport(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("ImportedVerticalTransport").transform;
            root.SetParent(parent, false);
            var baseCenter = new Vector3(center.x + 8.2f, floorY, center.z + 4.0f);

            // The source package names these meshes "Start" and "End", but they are
            // modular escalator pieces used repeatedly by its demo scene.  Scaling a
            // single module as a complete machine produces giant, incorrect cladding.
            // Build the complete bank here and reuse the imported trim/escalator
            // materials; the original modules remain packaged for later prefab study.
            BuildEscalatorLane(
                root,
                "EscalatorUp_Complete",
                baseCenter + Vector3.left * 3.15f,
                true,
                materials);
            BuildEscalatorLane(
                root,
                "EscalatorDown_Complete",
                baseCenter + Vector3.left * 1.15f,
                false,
                materials);
            BuildStairFlight(
                root,
                "Stairs_Complete",
                baseCenter + Vector3.right * 1.75f,
                materials);
            B1HeroGeometryFactory.Box(
                root,
                "VerticalTransportSign",
                baseCenter + new Vector3(0.7f, 3.62f, -2.75f),
                new Vector3(11.2f, 0.52f, 0.11f),
                materials.Sign);
            B1HeroGeometryFactory.Text(
                root,
                "VerticalTransportLabel",
                "站台层  扶梯 / 楼梯  TO TRAINS  ↓",
                baseCenter + new Vector3(0.7f, 3.63f, -2.68f),
                0.13f,
                Color.white);
        }

        private static void BuildEscalatorLane(
            Transform parent,
            string name,
            Vector3 lowerCenter,
            bool upward,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject(name).transform;
            root.SetParent(parent, false);
            const float width = 1.68f;
            const float run = 6.7f;
            const float rise = 2.75f;
            const int stepCount = 20;
            var direction = Vector3.back;
            var tread = run / stepCount;

            for (var index = 0; index < stepCount; index++)
            {
                var t = (index + 0.5f) / stepCount;
                var position = lowerCenter
                    + direction * (run * t)
                    + Vector3.up * (rise * (index + 1f) / stepCount - 0.065f);
                B1HeroGeometryFactory.Box(
                    root,
                    "EscalatorStep_" + index,
                    position,
                    new Vector3(width * 0.72f, 0.13f, tread * 0.92f),
                    materials.ImportedEscalator);
            }

            var upperCenter = lowerCenter + direction * run + Vector3.up * rise;
            for (var side = -1; side <= 1; side += 2)
            {
                var lateral = Vector3.right * (side * width * 0.48f);
                SlopedBox(
                    root,
                    "EscalatorGlass_" + side,
                    lowerCenter + lateral + Vector3.up * 0.43f,
                    upperCenter + lateral + Vector3.up * 0.43f,
                    new Vector2(0.055f, 0.68f),
                    materials.Glass);
                SlopedBox(
                    root,
                    "EscalatorSkirt_" + side,
                    lowerCenter + lateral + Vector3.up * 0.15f,
                    upperCenter + lateral + Vector3.up * 0.15f,
                    new Vector2(0.10f, 0.32f),
                    materials.ImportedTrim);
                Rail(
                    root,
                    "EscalatorHandrail_" + side,
                    lowerCenter + lateral + Vector3.up * 1.02f,
                    upperCenter + lateral + Vector3.up * 1.02f,
                    0.055f,
                    materials.DarkMetal);
            }

            B1HeroGeometryFactory.Box(
                root,
                "EscalatorLowerLanding",
                lowerCenter + Vector3.forward * 0.28f + Vector3.up * 0.09f,
                new Vector3(width, 0.18f, 0.82f),
                materials.BrushedSteel);
            B1HeroGeometryFactory.Box(
                root,
                "EscalatorUpperLanding",
                upperCenter + Vector3.back * 0.28f + Vector3.up * 0.09f,
                new Vector3(width, 0.18f, 0.82f),
                materials.BrushedSteel);
            B1HeroGeometryFactory.Box(
                root,
                upward ? "UpDirectionIndicator" : "DownDirectionIndicator",
                lowerCenter + new Vector3(0f, 0.72f, 0.48f),
                new Vector3(0.26f, 0.30f, 0.035f),
                upward ? materials.GreenLight : materials.BlueAccent);
        }

        private static void BuildStairFlight(
            Transform parent,
            string name,
            Vector3 lowerCenter,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject(name).transform;
            root.SetParent(parent, false);
            const float width = 2.45f;
            const float run = 6.7f;
            const float rise = 2.75f;
            const int stepCount = 18;
            var direction = Vector3.back;
            var tread = run / stepCount;

            for (var index = 0; index < stepCount; index++)
            {
                var height = rise * (index + 1f) / stepCount;
                B1HeroGeometryFactory.Box(
                    root,
                    "StairTread_" + index,
                    lowerCenter
                        + direction * (tread * (index + 0.5f))
                        + Vector3.up * (height * 0.5f),
                    new Vector3(width, height, tread + 0.018f),
                    index % 3 == 0 ? materials.ImportedTrim : materials.Floor);
            }

            var upperCenter = lowerCenter + direction * run + Vector3.up * rise;
            for (var side = -1; side <= 1; side += 2)
            {
                var lateral = Vector3.right * (side * width * 0.51f);
                Rail(
                    root,
                    "StairHandrail_" + side,
                    lowerCenter + lateral + Vector3.up * 0.96f,
                    upperCenter + lateral + Vector3.up * 0.96f,
                    0.045f,
                    materials.BrushedSteel);
                for (var post = 0; post <= 6; post++)
                {
                    var t = post / 6f;
                    var foot = Vector3.Lerp(lowerCenter, upperCenter, t) + lateral;
                    Rail(
                        root,
                        "StairBaluster_" + side + "_" + post,
                        foot,
                        foot + Vector3.up * 0.96f,
                        0.025f,
                        materials.BrushedSteel);
                }
            }
        }

        private static void Rail(
            Transform parent,
            string name,
            Vector3 start,
            Vector3 end,
            float diameter,
            Material material)
        {
            var delta = end - start;
            var rail = B1HeroGeometryFactory.Cylinder(
                parent,
                name,
                (start + end) * 0.5f,
                diameter * 0.5f,
                delta.magnitude,
                material);
            rail.transform.rotation = Quaternion.FromToRotation(Vector3.up, delta.normalized);
        }

        private static void SlopedBox(
            Transform parent,
            string name,
            Vector3 start,
            Vector3 end,
            Vector2 crossSection,
            Material material)
        {
            var delta = end - start;
            var box = B1HeroGeometryFactory.Box(
                parent,
                name,
                (start + end) * 0.5f,
                new Vector3(crossSection.x, crossSection.y, delta.magnitude),
                material);
            box.transform.rotation = Quaternion.FromToRotation(Vector3.forward, delta.normalized);
        }

        private static void BuildServiceProps(
            Transform parent,
            Vector3 center,
            float floorY,
            B1HeroMaterialLibrary materials)
        {
            var root = new GameObject("ImportedServiceProps").transform;
            root.SetParent(parent, false);

            PlaceModel(
                root,
                "SM_Info_Panel_01a",
                "InformationPanel_Imported",
                new Vector3(center.x + 15.7f, floorY + 0.64f, center.z - 1.9f),
                -90f,
                new Vector3(2.6f, 1.85f, 0.28f),
                false,
                new[] { materials.DarkMetal, materials.AdvertisingWhite, materials.BlueAccent });
            PlaceModel(
                root,
                "SM_Display_01a",
                "PassengerDisplay_Imported",
                new Vector3(center.x - 15.7f, floorY + 0.82f, center.z + 5.6f),
                90f,
                new Vector3(2.2f, 1.45f, 0.28f),
                false,
                new[] { materials.DarkMetal, materials.AdvertisingWhite });
            PlaceModel(
                root,
                "SM_Help_machine_01a",
                "HelpPoint_Imported",
                new Vector3(center.x + 14.0f, floorY, center.z + 7.8f),
                180f,
                new Vector3(0.82f, 1.65f, 0.62f),
                false,
                new[] { materials.WallBlue, materials.AdvertisingWhite, materials.DarkMetal });
            PlaceModel(
                root,
                "SM_Fire_Extinguisher_Cabinet_01a",
                "FireCabinet_Imported",
                new Vector3(center.x + 13.8f, floorY + 0.66f, center.z - 12.15f),
                180f,
                new Vector3(0.82f, 1.32f, 0.32f),
                false,
                new[] { materials.Wall, materials.Glass, materials.SafetyRed });
            PlaceModel(
                root,
                "SM_Fire_Extinguisher_01a",
                "FireExtinguisher_Imported",
                new Vector3(center.x + 14.75f, floorY, center.z - 11.95f),
                180f,
                new Vector3(0.34f, 0.82f, 0.34f),
                false,
                new[] { materials.SafetyRed, materials.DarkMetal });
        }

        private static GameObject PlaceModel(
            Transform parent,
            string resourceName,
            string instanceName,
            Vector3 basePosition,
            float yaw,
            Vector3 targetSize,
            bool alignLongestHorizontalAxis,
            IReadOnlyList<Material> palette)
        {
            var model = Resources.Load<GameObject>(ModelRoot + resourceName);
            if (model == null)
            {
                Debug.LogWarning("B1 imported station model is unavailable: " + resourceName);
                return null;
            }

            var instance = Object.Instantiate(model, parent, false);
            instance.name = instanceName;
            instance.transform.localPosition = Vector3.zero;
            instance.transform.localRotation = Quaternion.Euler(0f, yaw, 0f);
            instance.transform.localScale = Vector3.one;
            RemoveColliders(instance);
            ApplyMaterials(instance, palette);

            if (!TryGetBounds(instance, out var bounds))
            {
                DestroyObject(instance);
                return null;
            }

            if (alignLongestHorizontalAxis && bounds.size.x > bounds.size.z)
            {
                instance.transform.localRotation = Quaternion.Euler(0f, yaw + 90f, 0f);
                TryGetBounds(instance, out bounds);
            }

            var scale = Mathf.Min(
                targetSize.x / Mathf.Max(0.001f, bounds.size.x),
                targetSize.y / Mathf.Max(0.001f, bounds.size.y),
                targetSize.z / Mathf.Max(0.001f, bounds.size.z));
            instance.transform.localScale = Vector3.one * scale;
            TryGetBounds(instance, out bounds);
            instance.transform.position += basePosition
                - new Vector3(bounds.center.x, bounds.min.y, bounds.center.z);

            foreach (var child in instance.GetComponentsInChildren<Transform>(true))
                child.gameObject.isStatic = true;
            return instance;
        }

        private static void ApplyMaterials(GameObject instance, IReadOnlyList<Material> palette)
        {
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                var materialCount = Mathf.Max(1, renderer.sharedMaterials.Length);
                var assigned = new Material[materialCount];
                for (var index = 0; index < materialCount; index++)
                    assigned[index] = palette[Mathf.Min(index, palette.Count - 1)];
                renderer.sharedMaterials = assigned;
                renderer.shadowCastingMode = ShadowCastingMode.On;
                renderer.receiveShadows = true;
                renderer.motionVectorGenerationMode = MotionVectorGenerationMode.ForceNoMotion;
            }
        }

        private static bool TryGetBounds(GameObject instance, out Bounds bounds)
        {
            bounds = default;
            var hasBounds = false;
            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                if (!hasBounds)
                {
                    bounds = renderer.bounds;
                    hasBounds = true;
                }
                else
                {
                    bounds.Encapsulate(renderer.bounds);
                }
            }
            return hasBounds;
        }

        private static void RemoveColliders(GameObject instance)
        {
            foreach (var collider in instance.GetComponentsInChildren<Collider>(true))
                DestroyObject(collider);
        }

        private static void DestroyObject(Object target)
        {
            if (UnityEngine.Application.isPlaying)
                Object.Destroy(target);
            else
                Object.DestroyImmediate(target);
        }
    }
}
