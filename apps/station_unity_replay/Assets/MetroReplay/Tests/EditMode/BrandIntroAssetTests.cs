using System;
using System.Reflection;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class BrandIntroAssetTests
    {
        [Test]
        public void IntroBloom_IsMoreRestrainedThanTheStationLook()
        {
            Assert.That(BrandIntroBootstrap.IntroBloomIntensity, Is.EqualTo(0.025f));
            Assert.That(BrandIntroBootstrap.IntroBloomThreshold, Is.EqualTo(1.6f));
            Assert.That(BrandIntroBootstrap.IntroBloomScatter, Is.EqualTo(0.28f));
            Assert.That(BrandIntroBootstrap.IntroBloomIntensity, Is.LessThan(0.06f));
            Assert.That(BrandIntroBootstrap.IntroBloomThreshold, Is.GreaterThan(1.3f));
            Assert.That(BrandIntroBootstrap.IntroBloomScatter, Is.LessThan(0.5f));
        }

        [Test]
        public void CoinMeshSeparatesEdgeFrontAndBackMaterials()
        {
            var mesh = InvokeMeshFactory("Create", 1.6f, 0.3f, 64);
            try
            {
                Assert.That(mesh.subMeshCount, Is.EqualTo(3));
                Assert.That(mesh.GetTriangles(0).Length, Is.GreaterThan(0));
                Assert.That(mesh.GetTriangles(1).Length, Is.EqualTo(64 * 3));
                Assert.That(mesh.GetTriangles(2).Length, Is.EqualTo(64 * 3));
                Assert.That(mesh.bounds.size.x, Is.EqualTo(3.2f).Within(0.02f));
                Assert.That(mesh.bounds.size.z, Is.EqualTo(0.3f).Within(0.02f));
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(mesh);
            }
        }

        [Test]
        public void PerseusFaceTextureIsPackagedAsRuntimeResource()
        {
            var texture = Resources.Load<Texture2D>("BrandIntro/perseus-team");
            Assert.That(texture, Is.Not.Null);
            Assert.That(texture.width, Is.EqualTo(651));
            Assert.That(texture.height, Is.EqualTo(511));
            Assert.That(texture.width / (float)texture.height,
                Is.EqualTo(1.42f / 1.115f).Within(0.002f),
                "The intro artwork must keep the exact aspect ratio of the B1 billboard match cut.");
        }

        [Test]
        public void HiroshimaLogoUsesHighResolutionTransparentSource()
        {
            var texture = Resources.Load<Texture2D>("BrandIntro/hiroshima-university-logo");
            Assert.That(texture, Is.Not.Null);
            Assert.That(texture.width, Is.EqualTo(3840));
            Assert.That(texture.height, Is.EqualTo(1036));
            Assert.That(texture.isReadable, Is.True);
        }

        [Test]
        public void CrestLayoutCentersTheVisibleMarkInASquareCrop()
        {
            const int width = 20;
            const int height = 12;
            var pixels = new Color32[width * height];
            FillOpaqueRect(pixels, width, 2, 2, 5, 8);

            var bounds = BrandIntroCrestLayout.FindCenteredSquare(
                pixels,
                width,
                height,
                0.5f,
                0f);

            Assert.That(bounds.width, Is.EqualTo(bounds.height));
            Assert.That(bounds.xMin, Is.LessThanOrEqualTo(2));
            Assert.That(bounds.xMax, Is.GreaterThan(6));
            Assert.That(bounds.yMin, Is.LessThanOrEqualTo(2));
            Assert.That(bounds.yMax, Is.GreaterThan(9));
            Assert.That(
                bounds.xMin + (bounds.width - 1) * 0.5f,
                Is.EqualTo(4f).Within(0.5f));
            Assert.That(
                bounds.yMin + (bounds.height - 1) * 0.5f,
                Is.EqualTo(5.5f).Within(0.5f));
        }

        [Test]
        public void CrestLayoutIgnoresTheWordmarkToTheRight()
        {
            const int width = 30;
            const int height = 12;
            var pixels = new Color32[width * height];
            FillOpaqueRect(pixels, width, 2, 3, 4, 6);
            FillOpaqueRect(pixels, width, 18, 0, 12, 12);

            var bounds = BrandIntroCrestLayout.FindCenteredSquare(
                pixels,
                width,
                height,
                0.4f,
                0f);

            Assert.That(bounds.width, Is.EqualTo(6));
            Assert.That(bounds.xMin, Is.LessThanOrEqualTo(2));
            Assert.That(bounds.xMax, Is.GreaterThan(5));
            Assert.That(bounds.xMax, Is.LessThan(18));
        }

        [Test]
        public void GraphicMatchArtworkKeepsTheCoinScreenWidth()
        {
            var coinBounds = new Rect(300f, 200f, 420f, 420f);
            var artwork = BrandIntroGraphicMatch.CreateArtworkRect(
                coinBounds,
                651f / 511f);

            Assert.That(artwork.center, Is.EqualTo(coinBounds.center));
            Assert.That(artwork.width, Is.EqualTo(coinBounds.width).Within(0.001f));
            Assert.That(artwork.height, Is.EqualTo(coinBounds.width * 511f / 651f).Within(0.001f));
        }

        private static Mesh InvokeMeshFactory(string methodName, params object[] arguments)
        {
            var meshType = typeof(PassengerPool).Assembly.GetType(
                "MetroReplay.Presentation.BrandIntroCoinMesh");
            Assert.That(meshType, Is.Not.Null);
            var method = meshType.GetMethod(
                methodName,
                BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            Assert.That(method, Is.Not.Null);
            return (Mesh)method.Invoke(null, arguments);
        }

        private static void FillOpaqueRect(
            Color32[] pixels,
            int textureWidth,
            int x,
            int y,
            int width,
            int height)
        {
            for (var row = y; row < y + height; row++)
            {
                for (var column = x; column < x + width; column++)
                    pixels[row * textureWidth + column] = new Color32(255, 255, 255, 255);
            }
        }
    }
}
