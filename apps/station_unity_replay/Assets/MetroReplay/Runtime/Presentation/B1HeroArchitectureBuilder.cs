using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class B1HeroArchitectureBuilder
    {
        public static void Build(
            Transform parent,
            Vector3 shellCenter,
            Vector3 featureCenter,
            IReadOnlyList<Vector3> bayCenters,
            float floorY,
            float width,
            float depth,
            B1HeroMaterialLibrary materials)
        {
            const float clearHeight = 4.65f;
            var ceilingY = floorY + clearHeight;

            B1HeroGeometryFactory.Box(parent, "HeroFloor", shellCenter + Vector3.down * 0.09f,
                new Vector3(width, 0.18f, depth), materials.Floor);
            B1HeroGeometryFactory.Box(parent, "HeroCeiling", new Vector3(shellCenter.x, ceilingY, shellCenter.z),
                new Vector3(width, 0.18f, depth), materials.Ceiling);
            BuildWalls(parent, shellCenter, floorY, clearHeight, width, depth, materials);
            foreach (var bayCenter in bayCenters)
                BuildColumns(parent, bayCenter, floorY, clearHeight, materials);
            BuildCeilingDetails(parent, shellCenter, ceilingY, width, depth, materials);
            B1HeroFacilityBuilder.Build(parent, featureCenter, floorY, materials);
            B1HeroImportedAssetBuilder.Build(parent, featureCenter, floorY, materials);
        }

        private static void BuildWalls(
            Transform parent,
            Vector3 center,
            float floorY,
            float height,
            float width,
            float depth,
            B1HeroMaterialLibrary materials)
        {
            var wallY = floorY + height * 0.5f;
            var backZ = center.z - depth * 0.5f;
            B1HeroGeometryFactory.Box(parent, "HeroBackWall", new Vector3(center.x, wallY, backZ),
                new Vector3(width, height, 0.26f), materials.Wall);
            B1HeroGeometryFactory.Box(parent, "HeroLeftWall", new Vector3(center.x - width * 0.5f, wallY, center.z),
                new Vector3(0.26f, height, depth), materials.Wall);
            B1HeroGeometryFactory.Box(parent, "HeroRightWall", new Vector3(center.x + width * 0.5f, wallY, center.z),
                new Vector3(0.26f, height, depth), materials.Wall);

            B1HeroGeometryFactory.Box(parent, "BackWallBlueCladding",
                new Vector3(center.x, floorY + 1.15f, backZ + 0.15f),
                new Vector3(width - 0.45f, 2.10f, 0.045f), materials.WallBlue);
            B1HeroGeometryFactory.Box(parent, "BackWallWhiteCap",
                new Vector3(center.x, floorY + 3.45f, backZ + 0.15f),
                new Vector3(width - 0.45f, 1.80f, 0.045f), materials.Wall);
            B1HeroGeometryFactory.Box(parent, "BackWallSkirting",
                new Vector3(center.x, floorY + 0.07f, backZ + 0.18f),
                new Vector3(width - 0.35f, 0.14f, 0.07f), materials.DarkMetal);

            for (var x = center.x - width * 0.5f + 1.5f; x < center.x + width * 0.5f; x += 1.5f)
            {
                B1HeroGeometryFactory.Box(parent, "WallPanelJoint", new Vector3(x, wallY, backZ + 0.14f),
                    new Vector3(0.014f, height - 0.18f, 0.018f), materials.Black);
            }
            B1HeroGeometryFactory.Box(parent, "LineColorBand", new Vector3(center.x, floorY + 2.23f, backZ + 0.19f),
                new Vector3(width - 0.4f, 0.10f, 0.035f), materials.BlueAccent);

            BuildSideWallCladding(parent, center, floorY, width, depth, materials);
        }

        private static void BuildColumns(
            Transform parent,
            Vector3 center,
            float floorY,
            float height,
            B1HeroMaterialLibrary materials)
        {
            var offsets = new[]
            {
                new Vector2(-8.2f, 4.2f), new Vector2(8.2f, 4.2f),
                new Vector2(-8.2f, -6.3f), new Vector2(8.2f, -6.3f)
            };
            foreach (var offset in offsets)
            {
                var position = new Vector3(center.x + offset.x, floorY + height * 0.5f, center.z + offset.y);
                B1HeroGeometryFactory.Box(parent, "BlueCladColumn", position,
                    new Vector3(0.96f, height, 0.96f), materials.WallBlue);
                B1HeroGeometryFactory.Box(parent, "ColumnWhiteFace",
                    new Vector3(position.x, position.y + 0.24f, position.z + 0.493f),
                    new Vector3(0.70f, height - 0.70f, 0.025f), materials.Wall);
                B1HeroGeometryFactory.Box(parent, "ColumnSteelBase",
                    new Vector3(position.x, floorY + 0.10f, position.z),
                    new Vector3(1.04f, 0.20f, 1.04f), materials.DarkMetal);
            }
        }

        private static void BuildCeilingDetails(
            Transform parent,
            Vector3 center,
            float ceilingY,
            float width,
            float depth,
            B1HeroMaterialLibrary materials)
        {
            B1HeroGeometryFactory.Box(parent, "CeilingBlueSpine",
                new Vector3(center.x, ceilingY - 0.16f, center.z),
                new Vector3(1.25f, 0.08f, depth - 0.8f), materials.WallBlue);

            var revealLimit = width * 0.5f - 1.6f;
            for (var xOffset = -revealLimit; xOffset <= revealLimit; xOffset += 2f)
            {
                B1HeroGeometryFactory.Box(parent, "CeilingReveal",
                    new Vector3(center.x + xOffset, ceilingY - 0.18f, center.z),
                    new Vector3(0.045f, 0.10f, depth - 1f), materials.Black);
            }
            var lightLimit = width * 0.5f - 3f;
            for (var xOffset = -lightLimit; xOffset <= lightLimit; xOffset += 4f)
            {
                B1HeroGeometryFactory.Box(parent, "LinearLight",
                    new Vector3(center.x + xOffset, ceilingY - 0.255f, center.z + 0.2f),
                    new Vector3(0.19f, 0.045f, depth - 3.5f), materials.Light);
            }
            var ribLimit = depth * 0.5f - 2f;
            for (var zOffset = -ribLimit; zOffset <= ribLimit; zOffset += 4f)
            {
                B1HeroGeometryFactory.Box(parent, "CeilingCrossRib",
                    new Vector3(center.x, ceilingY - 0.22f, center.z + zOffset),
                    new Vector3(width - 2f, 0.10f, 0.10f), materials.BrushedSteel);
            }
        }

        private static void BuildSideWallCladding(
            Transform parent,
            Vector3 center,
            float floorY,
            float width,
            float depth,
            B1HeroMaterialLibrary materials)
        {
            var sideY = floorY + 1.18f;
            var leftX = center.x - width * 0.5f + 0.15f;
            var rightX = center.x + width * 0.5f - 0.15f;
            B1HeroGeometryFactory.Box(parent, "LeftBlueWall", new Vector3(leftX, sideY, center.z),
                new Vector3(0.04f, 2.18f, depth - 0.5f), materials.WallBlue);
            B1HeroGeometryFactory.Box(parent, "RightBlueWall", new Vector3(rightX, sideY, center.z),
                new Vector3(0.04f, 2.18f, depth - 0.5f), materials.WallBlue);
        }
    }
}
