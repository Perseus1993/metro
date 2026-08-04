using System.IO;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class PassengerSkinAtlasTests
    {
        [Test]
        public void PackagesGeneratedCommuterAtlas()
        {
            var path = Path.Combine(
                UnityEngine.Application.streamingAssetsPath,
                "PassengerSkins",
                "commuter_skin_atlas_v1.png");

            Assert.That(File.Exists(path), Is.True, path);
            Assert.That(new FileInfo(path).Length, Is.GreaterThan(1024));
        }

        [TestCase(0, 0f, 0f)]
        [TestCase(1, 0.5f, 0f)]
        [TestCase(2, 0f, 0.5f)]
        [TestCase(3, 0.5f, 0.5f)]
        public void MapsEachVariantToOneAtlasQuadrant(int variant, float offsetX, float offsetY)
        {
            var transform = PassengerSkinAtlas.GetUvTransform(variant);

            Assert.That(transform.x, Is.EqualTo(0.5f));
            Assert.That(transform.y, Is.EqualTo(0.5f));
            Assert.That(transform.z, Is.EqualTo(offsetX));
            Assert.That(transform.w, Is.EqualTo(offsetY));
        }

        [Test]
        public void SelectsSkinDeterministicallyFromPassengerId()
        {
            for (var id = 0; id < 300; id++)
            {
                var first = PassengerSkinAtlas.GetVariantIndex(id);
                var second = PassengerSkinAtlas.GetVariantIndex(id);
                Assert.That(first, Is.EqualTo(second));
                Assert.That(first, Is.InRange(0, PassengerSkinAtlas.VariantCount - 1));
            }
        }
    }
}
