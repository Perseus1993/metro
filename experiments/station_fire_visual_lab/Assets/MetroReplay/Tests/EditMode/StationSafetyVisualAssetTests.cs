using System.Linq;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class StationSafetyVisualAssetTests
    {
        [TestCase("WaterBarrier_Red")]
        [TestCase("WaterBarrier_Yellow")]
        public void GeneratedWaterBarrierIsCc0VisualOnlyAndColliderFree(string resourceName)
        {
            var prefab = Resources.Load<GameObject>("StationOperations/Prefabs/" + resourceName);
            Assert.That(prefab, Is.Not.Null);
            Assert.That(prefab.GetComponentsInChildren<Renderer>(true), Is.Not.Empty);
            Assert.That(prefab.GetComponentsInChildren<Collider>(true), Is.Empty);
            Assert.That(prefab.GetComponentsInChildren<Rigidbody>(true), Is.Empty);
            var identity = prefab.GetComponent<VisualOnlyStationAssetIdentity>();
            Assert.That(identity, Is.Not.Null);
            Assert.That(identity.Licence, Is.EqualTo("CC0-1.0"));
            Assert.That(identity.AffectsSimulation, Is.False);
            Assert.That(
                prefab.GetComponentsInChildren<Renderer>(true)
                    .SelectMany(renderer => renderer.sharedMaterials)
                    .All(material => material != null && material.shader != null),
                Is.True);
        }

        [Test]
        public void FireVisualDisclaimerNamesAllNonAuthoritativeLayers()
        {
            var source = System.IO.File.ReadAllText(
                "Assets/MetroReplay/Runtime/Experimental/StationFireVisualDemo.cs");
            StringAssert.Contains("火焰、人员与全部试装设施均未参与路径计算", source);
        }
    }
}
