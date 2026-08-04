using System.IO;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class StationElementTrialAssetTests
    {
        [Test]
        public void PackagesCc0StationElementTrialModels()
        {
            var decor = Path.Combine(UnityEngine.Application.streamingAssetsPath, "Decor");
            var expected = new[]
            {
                Path.Combine("KenneyConveyorKit", "scanner-low.glb"),
                Path.Combine("KenneyConveyorKit", "scanner-high.glb"),
                Path.Combine("KenneyConveyorKit", "conveyor-long-sides.glb"),
                Path.Combine("PolyHaven", "fire_alarm", "fire_alarm_1k.gltf"),
                Path.Combine("PolyHaven", "utility_box_01", "utility_box_01_1k.gltf"),
                Path.Combine("PolyHaven", "wheelchair_01", "wheelchair_01_1k.gltf"),
                Path.Combine("PolyHaven", "CoffeeCart_01", "CoffeeCart_01_1k.gltf"),
                Path.Combine("PolyHaven", "all_purpose_cleaner", "all_purpose_cleaner_1k.gltf"),
                Path.Combine("PolyHaven", "plastic_broom", "plastic_broom_1k.gltf"),
                Path.Combine("PolyHaven", "wall_clock", "wall_clock_1k.gltf"),
                "STATION_ELEMENT_TRIAL_PROVENANCE.md"
            };

            foreach (var relativePath in expected)
                Assert.That(File.Exists(Path.Combine(decor, relativePath)), Is.True, relativePath);
        }

        [Test]
        public void TrialLayerExplicitlyDeclaresVisualOnlyBoundary()
        {
            var source = File.ReadAllText(
                "Assets/MetroReplay/Runtime/Experimental/StationElementTrialLayer.cs");
            StringAssert.Contains("Non-authoritative", source);
            StringAssert.Contains("VisualOnlyStationAssetIdentity", source);
            StringAssert.Contains("CC0-1.0", source);
            StringAssert.Contains("plastic_broom", source);
            StringAssert.DoesNotContain("KenneyConveyorKit", source);
            StringAssert.DoesNotContain("CoffeeCart_01", source);
        }
    }
}
