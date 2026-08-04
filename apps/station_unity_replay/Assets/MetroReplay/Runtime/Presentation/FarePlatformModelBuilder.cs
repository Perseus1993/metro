using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class FarePlatformModelBuilder
    {
        public static GameObject BuildFareGates(
            Transform parent, string id, Vector3 center, float width, float depth,
            float rotationDegrees, StationFacilityMaterials materials)
        {
            var root = CreateRoot(parent, id, center, rotationDegrees);
            width = Mathf.Max(width, 2.1f);
            depth = Mathf.Max(depth, 1.45f);
            var lanes = Mathf.Clamp(Mathf.RoundToInt(width / 0.95f), 2, 12);
            var laneWidth = width / lanes;

            for (var index = 0; index <= lanes; index++)
            {
                var x = -width * 0.5f + index * laneWidth;
                FacilityGeometry.RoundedPrism(root, "GatePedestal_" + index,
                    new Vector3(x, 0.48f, 0f),
                    new Vector3(0.25f, 0.96f, depth), 0.1f,
                    index == 0 || index == lanes ? materials.DarkMetal : materials.GateBlue);
                FacilityGeometry.RoundedPrism(root, "CardReader_" + index,
                    new Vector3(x, 1.00f, -depth * 0.24f),
                    new Vector3(0.31f, 0.10f, 0.42f), 0.08f, materials.DarkMetal);
                FacilityGeometry.Box(root, "ReaderLight_" + index,
                    new Vector3(x, 1.055f, -depth * 0.24f),
                    new Vector3(0.12f, 0.018f, 0.20f), materials.Green);
            }

            for (var lane = 0; lane < lanes; lane++)
            {
                var x = -width * 0.5f + (lane + 0.5f) * laneWidth;
                FacilityGeometry.Box(root, "GlassWingLeft_" + lane,
                    new Vector3(x - laneWidth * 0.22f, 0.69f, 0.20f),
                    new Vector3(laneWidth * 0.43f, 0.56f, 0.035f), materials.Glass);
                FacilityGeometry.Box(root, "GlassWingRight_" + lane,
                    new Vector3(x + laneWidth * 0.22f, 0.69f, 0.20f),
                    new Vector3(laneWidth * 0.43f, 0.56f, 0.035f), materials.Glass);
                FacilityGeometry.Box(root, "LaneArrow_" + lane,
                    new Vector3(x, 0.06f, -depth * 0.38f),
                    new Vector3(0.22f, 0.02f, 0.38f), materials.Green);
            }
            return root.gameObject;
        }

        public static GameObject BuildPlatformDoors(
            Transform parent, string id, Vector3 center, float sizeX, float sizeZ,
            float rotationDegrees, StationFacilityMaterials materials)
        {
            var alongZ = sizeZ > sizeX;
            var length = Mathf.Max(alongZ ? sizeZ : sizeX, 2.8f);
            var root = CreateRoot(parent, id, center, rotationDegrees + (alongZ ? 90f : 0f));
            const float height = 2.35f;
            const float depth = 0.18f;
            var openingWidth = Mathf.Clamp(length * 0.72f, 1.85f, 2.24f);
            var fixedWidth = Mathf.Max(0.18f, (length - openingWidth) * 0.5f);

            FacilityGeometry.Box(root, "PlatformDoorHeader", new Vector3(0f, height - 0.13f, 0f),
                new Vector3(length + 0.18f, 0.26f, 0.31f), materials.DarkMetal);
            FacilityGeometry.Box(root, "PlatformDoorSill", new Vector3(0f, 0.08f, 0f),
                new Vector3(length + 0.18f, 0.16f, 0.28f), materials.Steel);
            foreach (var x in new[]
            {
                -length * 0.5f,
                -openingWidth * 0.5f,
                openingWidth * 0.5f,
                length * 0.5f
            })
            {
                FacilityGeometry.RoundedPrism(root, "PlatformDoorPost",
                    new Vector3(x, height * 0.5f, 0f),
                    new Vector3(0.10f, height, 0.23f), 0.025f, materials.DoorFrame);
            }

            var fixedCenter = openingWidth * 0.5f + fixedWidth * 0.5f;
            FacilityGeometry.Box(root, "PlatformDoorFixedGlass_Left",
                new Vector3(-fixedCenter, 1.18f, 0f),
                new Vector3(Mathf.Max(0.10f, fixedWidth - 0.10f), 1.86f, depth * 0.45f), materials.Glass);
            FacilityGeometry.Box(root, "PlatformDoorFixedGlass_Right",
                new Vector3(fixedCenter, 1.18f, 0f),
                new Vector3(Mathf.Max(0.10f, fixedWidth - 0.10f), 1.86f, depth * 0.45f), materials.Glass);

            BuildSlidingLeaf(root, "PlatformDoorLeaf_Left", -openingWidth * 0.25f,
                openingWidth * 0.5f - 0.07f, height, depth, materials);
            BuildSlidingLeaf(root, "PlatformDoorLeaf_Right", openingWidth * 0.25f,
                openingWidth * 0.5f - 0.07f, height, depth, materials);

            FacilityGeometry.Box(root, "PlatformDoorStatusLight",
                new Vector3(0f, height - 0.12f, -0.17f),
                new Vector3(0.32f, 0.075f, 0.035f), materials.Green);
            return root.gameObject;
        }

        private static void BuildSlidingLeaf(
            Transform parent,
            string name,
            float centerX,
            float width,
            float height,
            float depth,
            StationFacilityMaterials materials)
        {
            var leaf = new GameObject(name).transform;
            leaf.SetParent(parent, false);
            leaf.localPosition = new Vector3(centerX, 1.18f, 0f);
            FacilityGeometry.Box(leaf, "DoorGlass", Vector3.zero,
                new Vector3(width, 1.86f, depth * 0.55f), materials.Glass);
            FacilityGeometry.Box(leaf, "DoorVerticalFrame",
                new Vector3(Mathf.Sign(centerX) * width * 0.47f, 0f, -0.055f),
                new Vector3(0.055f, 1.90f, 0.045f), materials.DoorFrame);
            FacilityGeometry.Box(leaf, "DoorWarningStripe",
                new Vector3(0f, 0.25f, -0.105f),
                new Vector3(width * 0.62f, 0.055f, 0.025f), materials.Amber);
        }

        private static Transform CreateRoot(
            Transform parent, string id, Vector3 center, float rotationDegrees)
        {
            var root = new GameObject(id).transform;
            root.SetParent(parent, false);
            root.position = center;
            root.rotation = Quaternion.Euler(0f, -rotationDegrees, 0f);
            return root;
        }
    }
}
