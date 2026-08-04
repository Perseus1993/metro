using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class VerticalFacilityModelBuilder
    {
        public static GameObject Build(
            Transform parent, string id, string kind, Vector3 start, Vector3 end,
            StationFacilityMaterials materials)
        {
            if (kind.Equals("elevator", System.StringComparison.OrdinalIgnoreCase))
                return BuildElevator(parent, id, start, end, materials);
            var route = VerticalFacilityRouteResolver.Resolve(kind, start, end);
            return kind.Equals("stairs", System.StringComparison.OrdinalIgnoreCase)
                ? BuildStairs(parent, id, route.Middle, route.LowAnchor, materials)
                : BuildEscalator(parent, id, route.Middle, route.LowAnchor, materials);
        }

        private static GameObject BuildStairs(
            Transform parent, string id, Vector3 start, Vector3 end,
            StationFacilityMaterials materials)
        {
            var root = CreateSlopeRoot(parent, id, start, end, out var run, out var rise);
            const float width = 2.35f;
            var steps = SlopeStepCount(run, rise, 0.30f, 0.18f, 6, 80);
            var tread = run / steps;
            var riser = Mathf.Max(0.16f, Mathf.Abs(rise) / steps + 0.015f);
            for (var index = 0; index < steps; index++)
            {
                var top = rise * (index + 1f) / steps;
                FacilityGeometry.Box(root, "StairTread_" + index,
                    new Vector3(0f, top - riser * 0.5f,
                        tread * (index + 0.5f)),
                    new Vector3(width, riser, tread + 0.025f), materials.Step);
            }
            AddSlopeRails(root, run, rise, width, 1.0f, materials.Steel);
            FacilityGeometry.SlopedBox(root, "StairStringerLeft",
                new Vector3(-width * 0.52f, 0f, 0f), new Vector3(-width * 0.52f, rise, run),
                new Vector2(0.12f, 0.18f), materials.DarkMetal);
            FacilityGeometry.SlopedBox(root, "StairStringerRight",
                new Vector3(width * 0.52f, 0f, 0f), new Vector3(width * 0.52f, rise, run),
                new Vector2(0.12f, 0.18f), materials.DarkMetal);
            return root.gameObject;
        }

        private static GameObject BuildEscalator(
            Transform parent, string id, Vector3 start, Vector3 end,
            StationFacilityMaterials materials)
        {
            var root = CreateSlopeRoot(parent, id, start, end, out var run, out var rise);
            const float width = 1.75f;
            var steps = SlopeStepCount(run, rise, 0.38f, 0.20f, 8, 72);
            var tread = run / steps;
            var riser = Mathf.Max(0.13f, Mathf.Abs(rise) / steps + 0.012f);
            for (var index = 0; index < steps; index++)
            {
                var y = rise * (index + 0.5f) / steps;
                FacilityGeometry.Box(root, "EscalatorStep_" + index,
                    new Vector3(0f, y, tread * (index + 0.5f)),
                    new Vector3(width * 0.76f, riser, Mathf.Max(0.04f, tread - 0.012f)),
                    materials.Step);
            }
            for (var side = -1; side <= 1; side += 2)
            {
                var x = side * width * 0.48f;
                FacilityGeometry.SlopedBox(root, "EscalatorGlass_" + side,
                    new Vector3(x, 0.25f, 0f), new Vector3(x, rise + 0.25f, run),
                    new Vector2(0.055f, 0.76f), materials.Glass);
                FacilityGeometry.Rail(root, "EscalatorHandrail_" + side,
                    new Vector3(x, 1.03f, 0f), new Vector3(x, rise + 1.03f, run),
                    0.055f, materials.Rubber);
            }
            FacilityGeometry.RoundedPrism(root, "EscalatorLandingLower",
                new Vector3(0f, 0.09f, -0.35f), new Vector3(width, 0.18f, 0.75f),
                0.08f, materials.Steel);
            FacilityGeometry.RoundedPrism(root, "EscalatorLandingUpper",
                new Vector3(0f, rise + 0.09f, run + 0.35f), new Vector3(width, 0.18f, 0.75f),
                0.08f, materials.Steel);
            return root.gameObject;
        }

        private static GameObject BuildElevator(
            Transform parent, string id, Vector3 start, Vector3 end,
            StationFacilityMaterials materials)
        {
            var root = new GameObject(id).transform;
            root.SetParent(parent, false);
            root.position = start;
            var vertical = end.y - start.y;
            var shaftDirection = Mathf.Sign(vertical == 0f ? 1f : vertical);
            var top = Vector3.up * vertical;

            for (var x = -1.15f; x <= 1.15f; x += 2.3f)
            {
                for (var z = -1.05f; z <= 1.05f; z += 2.1f)
                    FacilityGeometry.Rail(root, "ShaftPost", new Vector3(x, 0f, z),
                        new Vector3(x, vertical, z), 0.07f, materials.DarkMetal);
            }
            BuildElevatorPortal(root, Vector3.zero, materials, "Lower");
            BuildElevatorPortal(root, top, materials, "Upper");
            var car = new GameObject("ElevatorCar").transform;
            car.SetParent(root, false);
            FacilityGeometry.RoundedPrism(car, "ElevatorCabin",
                new Vector3(0f, 1.18f, 0f), new Vector3(2.05f, 2.30f, 1.95f),
                0.10f, materials.DoorPanel);
            FacilityGeometry.Box(car, "CabinFrontGlass",
                new Vector3(0f, 1.22f, -0.99f), new Vector3(1.72f, 1.62f, 0.035f),
                materials.Glass);
            FacilityGeometry.Box(root, "ShaftTop",
                new Vector3(0f, vertical + shaftDirection * 0.10f, 0f),
                new Vector3(2.55f, 0.20f, 2.35f), materials.DarkMetal);
            return root.gameObject;
        }

        private static void BuildElevatorPortal(
            Transform root, Vector3 center,
            StationFacilityMaterials materials, string suffix)
        {
            var y = center.y + 1.18f;
            FacilityGeometry.Box(root, "PortalLeft_" + suffix,
                new Vector3(-1.02f, y, -1.10f), new Vector3(0.22f, 2.38f, 0.18f), materials.Steel);
            FacilityGeometry.Box(root, "PortalRight_" + suffix,
                new Vector3(1.02f, y, -1.10f), new Vector3(0.22f, 2.38f, 0.18f), materials.Steel);
            FacilityGeometry.Box(root, "PortalHeader_" + suffix,
                new Vector3(0f, y + 1.10f, -1.10f),
                new Vector3(2.25f, 0.20f, 0.18f), materials.DarkMetal);
            FacilityGeometry.Box(root, "DoorLeft_" + suffix,
                new Vector3(-0.47f, y, -1.115f), new Vector3(0.90f, 2.05f, 0.07f), materials.DoorPanel);
            FacilityGeometry.Box(root, "DoorRight_" + suffix,
                new Vector3(0.47f, y, -1.115f), new Vector3(0.90f, 2.05f, 0.07f), materials.DoorPanel);
            FacilityGeometry.Box(root, "FloorIndicator_" + suffix,
                new Vector3(0f, y + 1.31f, -1.205f),
                new Vector3(0.32f, 0.11f, 0.025f), materials.Green);
        }

        private static Transform CreateSlopeRoot(
            Transform parent, string id, Vector3 start, Vector3 end,
            out float run, out float rise)
        {
            var flat = new Vector3(end.x - start.x, 0f, end.z - start.z);
            run = Mathf.Max(flat.magnitude, 1.8f);
            rise = end.y - start.y;
            var root = new GameObject(id).transform;
            root.SetParent(parent, false);
            root.position = start;
            root.rotation = Quaternion.Euler(0f, Mathf.Atan2(flat.x, flat.z) * Mathf.Rad2Deg, 0f);
            return root;
        }

        private static void AddSlopeRails(
            Transform root, float run, float rise, float width, float railHeight, Material material)
        {
            for (var side = -1; side <= 1; side += 2)
            {
                var x = side * width * 0.50f;
                FacilityGeometry.Rail(root, "StairHandrail_" + side,
                    new Vector3(x, railHeight, 0f), new Vector3(x, rise + railHeight, run),
                    0.045f, material);
                for (var part = 0; part <= 4; part++)
                {
                    var t = part / 4f;
                    var basePoint = new Vector3(x, rise * t, run * t);
                    FacilityGeometry.Rail(root, "StairBaluster", basePoint,
                        basePoint + Vector3.up * railHeight, 0.025f, material);
                }
            }
        }

        private static int SlopeStepCount(
            float run,
            float rise,
            float maximumTreadDepth,
            float maximumRiserHeight,
            int minimum,
            int maximum)
        {
            var horizontalCount = Mathf.CeilToInt(run / maximumTreadDepth);
            var verticalCount = Mathf.CeilToInt(Mathf.Abs(rise) / maximumRiserHeight);
            return Mathf.Clamp(Mathf.Max(horizontalCount, verticalCount), minimum, maximum);
        }
    }
}
