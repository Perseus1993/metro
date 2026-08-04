using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class B1HeroFareGateBuilder
    {
        public static void Build(
            Transform parent,
            Vector3 center,
            float totalWidth,
            float floorY,
            B1HeroMaterialLibrary materials,
            string rootName,
            bool isExit)
        {
            const float standardSpacing = 0.98f;
            const float accessibleSpacing = 1.25f;
            var lanes = Mathf.Clamp(
                Mathf.RoundToInt((Mathf.Max(4f, totalWidth) - accessibleSpacing) / standardSpacing) + 1,
                4,
                12);
            var accessibleLane = lanes - 1;
            var bankSpan = standardSpacing * (lanes - 1) + accessibleSpacing;
            var left = center.x - bankSpan * 0.5f;
            var root = new GameObject(rootName).transform;
            root.SetParent(parent, false);

            var pedestalX = left;
            BuildPedestal(root, new Vector3(pedestalX, floorY, center.z), materials, 0);
            for (var lane = 0; lane < lanes; lane++)
            {
                var spacing = lane == accessibleLane ? accessibleSpacing : standardSpacing;
                var nextPedestalX = pedestalX + spacing;
                var laneCenter = (pedestalX + nextPedestalX) * 0.5f;
                BuildPedestal(root, new Vector3(nextPedestalX, floorY, center.z), materials, lane + 1);
                BuildGlassFlaps(root, new Vector3(laneCenter, floorY, center.z), spacing, materials);
                BuildLaneIndicator(
                    root,
                    new Vector3(nextPedestalX, floorY, center.z + 0.77f),
                    materials,
                    isExit);
                if (lane == accessibleLane)
                    BuildAccessibleRoute(root, new Vector3(laneCenter, floorY, center.z), materials);
                pedestalX = nextPedestalX;
            }

            BuildOverheadSign(
                root,
                new Vector3(center.x, floorY, center.z - 0.65f),
                bankSpan,
                materials,
                isExit);
        }

        private static void BuildPedestal(
            Transform parent,
            Vector3 basePosition,
            B1HeroMaterialLibrary materials,
            int index)
        {
            B1HeroGeometryFactory.Box(parent, $"GatePedestal_{index}",
                basePosition + Vector3.up * 0.45f,
                new Vector3(0.28f, 0.90f, 1.48f), materials.BrushedSteel);
            B1HeroGeometryFactory.Box(parent, "GateBlueEndCap",
                basePosition + new Vector3(0f, 0.54f, 0.73f),
                new Vector3(0.29f, 0.52f, 0.055f), materials.WallBlue);
            B1HeroGeometryFactory.Box(parent, "GateTop",
                basePosition + new Vector3(0f, 0.935f, 0f),
                new Vector3(0.30f, 0.075f, 1.38f), materials.DarkMetal);
            B1HeroGeometryFactory.Box(parent, "ReaderScreen",
                basePosition + new Vector3(0f, 0.98f, 0.39f),
                new Vector3(0.19f, 0.025f, 0.31f), materials.GreenLight);
            B1HeroGeometryFactory.Box(parent, "GateFoot",
                basePosition + new Vector3(0f, 0.055f, 0f),
                new Vector3(0.34f, 0.11f, 1.58f), materials.DarkMetal);
        }

        private static void BuildGlassFlaps(
            Transform parent,
            Vector3 laneCenter,
            float spacing,
            B1HeroMaterialLibrary materials)
        {
            var passageWidth = spacing - 0.28f;
            var wingWidth = passageWidth * 0.50f;
            var wingOffset = passageWidth * 0.25f;
            var left = B1HeroGeometryFactory.Box(parent, "GlassWingLeft",
                laneCenter + new Vector3(-wingOffset, 0.62f, -0.02f),
                new Vector3(wingWidth, 0.54f, 0.028f), materials.Glass);
            left.transform.rotation = Quaternion.Euler(0f, 8f, 0f);
            var right = B1HeroGeometryFactory.Box(parent, "GlassWingRight",
                laneCenter + new Vector3(wingOffset, 0.62f, -0.02f),
                new Vector3(wingWidth, 0.54f, 0.028f), materials.Glass);
            right.transform.rotation = Quaternion.Euler(0f, -8f, 0f);
        }

        private static void BuildLaneIndicator(
            Transform parent,
            Vector3 position,
            B1HeroMaterialLibrary materials,
            bool isExit)
        {
            B1HeroGeometryFactory.Box(parent, "LaneIndicator",
                position + Vector3.up * 0.79f,
                new Vector3(0.18f, 0.14f, 0.035f), materials.GreenLight);
            B1HeroGeometryFactory.Text(parent, "LaneArrow", isExit ? "↓" : "↑",
                position + new Vector3(0f, 0.79f, 0.022f), 0.075f, Color.white);
        }

        private static void BuildAccessibleRoute(
            Transform parent,
            Vector3 laneCenter,
            B1HeroMaterialLibrary materials)
        {
            B1HeroGeometryFactory.Box(parent, "AccessibleTactileRoute",
                laneCenter + new Vector3(0f, 0.018f, 5.8f),
                new Vector3(0.30f, 0.026f, 10.1f), materials.Tactile);
            B1HeroGeometryFactory.Box(parent, "AccessibleWarningTactile",
                laneCenter + new Vector3(0f, 0.020f, 1.05f),
                new Vector3(1.02f, 0.030f, 0.36f), materials.Tactile);
            B1HeroGeometryFactory.Text(parent, "AccessibleLaneLabel", "无障碍",
                laneCenter + new Vector3(0f, 1.30f, 0.79f), 0.075f, Color.white);
        }

        private static void BuildOverheadSign(
            Transform parent,
            Vector3 gateCenter,
            float bankSpan,
            B1HeroMaterialLibrary materials,
            bool isExit)
        {
            const float signY = 3.16f;
            var signWidth = Mathf.Max(9.7f, bankSpan + 1.3f);
            B1HeroGeometryFactory.Box(parent, "WayfindingSign",
                gateCenter + Vector3.up * signY,
                new Vector3(signWidth, 0.68f, 0.13f), materials.Sign);
            B1HeroGeometryFactory.Box(parent, "SignAccent",
                gateCenter + new Vector3(0f, signY - 0.28f, 0.078f),
                new Vector3(signWidth - 0.28f, 0.075f, 0.025f), materials.BlueAccent);
            B1HeroGeometryFactory.Text(parent, "StationName",
                isExit
                    ? "← 出口 A / B       出站  EXIT  ↓       无障碍电梯 →"
                    : "进站  ENTRY  ↑       乘车  TO TRAINS  ↓       无障碍通道 →",
                gateCenter + new Vector3(0f, signY + 0.035f, 0.075f), 0.155f, Color.white);

            var hangerOffset = signWidth * 0.43f;
            for (var side = -1; side <= 1; side += 2)
            {
                B1HeroGeometryFactory.Box(parent, "SignHanger",
                    gateCenter + new Vector3(side * hangerOffset, 3.83f, 0f),
                    new Vector3(0.05f, 0.72f, 0.05f), materials.DarkMetal);
            }
        }
    }
}
