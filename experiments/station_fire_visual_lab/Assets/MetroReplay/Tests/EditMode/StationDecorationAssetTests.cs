using System.IO;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class StationDecorationAssetTests
    {
        [Test]
        public void PackagesCc0DecorationModelsAndProvenance()
        {
            var root = Path.Combine(UnityEngine.Application.streamingAssetsPath, "Decor");
            var expected = new[]
            {
                Path.Combine("KenneyFurnitureKit", "bench.glb"),
                Path.Combine("KenneyFurnitureKit", "trashcan.glb"),
                Path.Combine("KenneyFurnitureKit", "lampSquareCeiling.glb"),
                Path.Combine("KenneyFurnitureKit", "pottedPlant.glb"),
                Path.Combine("KenneyFurnitureKit", "televisionModern.glb"),
                Path.Combine("KenneyFurnitureKit", "kitchenCoffeeMachine.glb"),
                Path.Combine("KenneyFurnitureKit", "doorwayFront.glb"),
                Path.Combine("PolyHaven", "security_camera_01", "security_camera_01_1k.gltf"),
                Path.Combine("PolyHaven", "korean_fire_extinguisher_01", "korean_fire_extinguisher_01_1k.gltf"),
                "THIRD_PARTY_ASSETS.md"
            };

            foreach (var relativePath in expected)
                Assert.That(File.Exists(Path.Combine(root, relativePath)), Is.True, relativePath);
        }
    }
}
