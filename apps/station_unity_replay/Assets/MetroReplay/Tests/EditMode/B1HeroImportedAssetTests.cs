using System;
using System.IO;
using System.Reflection;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class B1HeroImportedAssetTests
    {
        private const string ModelRoot =
            "MetroReplay/ThirdParty/SubwayTerminalPrototype/Models/";

        [Test]
        public void PackagesSelectedPrototypeModelsAndProvenance()
        {
            var modelNames = new[]
            {
                "SM_Escalator_Strt_01a",
                "SM_Escalator_End_01a",
                "SM_Staris_01a",
                "SM_Stairs_Railing_01a",
                "SM_Info_Panel_01a",
                "SM_Display_01a",
                "SM_Help_machine_01a",
                "SM_Fire_Extinguisher_01a",
                "SM_Fire_Extinguisher_Cabinet_01a"
            };

            foreach (var modelName in modelNames)
                Assert.That(Resources.Load<GameObject>(ModelRoot + modelName), Is.Not.Null, modelName);

            var provenancePath = Path.Combine(
                UnityEngine.Application.dataPath,
                "MetroReplay",
                "ThirdParty",
                "SubwayTerminalPrototype",
                "PROVENANCE.md");
            Assert.That(File.Exists(provenancePath), Is.True);
            StringAssert.Contains("prototype only", File.ReadAllText(provenancePath).ToLowerInvariant());
        }

        [Test]
        public void ImportedHeroLayerBuildsWithoutSimulationColliders()
        {
            var assembly = typeof(StationDecorationLayer).Assembly;
            var materialType = assembly.GetType(
                "MetroReplay.Presentation.B1HeroMaterialLibrary",
                true);
            var builderType = assembly.GetType(
                "MetroReplay.Presentation.B1HeroImportedAssetBuilder",
                true);
            var materials = Activator.CreateInstance(
                materialType!,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null,
                null,
                null);
            var root = new GameObject("B1ImportedAssetTestRoot");
            try
            {
                var build = builderType!.GetMethod(
                    "Build",
                    BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                Assert.That(build, Is.Not.Null);
                build!.Invoke(null, new[] { root.transform, Vector3.zero, 0f, materials });

                var importedRoot = root.transform.Find("ImportedStationAssets");
                Assert.That(importedRoot, Is.Not.Null);
                Assert.That(importedRoot!.Find("ImportedVerticalTransport"), Is.Not.Null);
                Assert.That(importedRoot.GetComponentsInChildren<Renderer>(true).Length, Is.GreaterThan(0));
                Assert.That(importedRoot.GetComponentsInChildren<Collider>(true), Is.Empty,
                    "Imported decoration must not alter simulation or navigation collision.");
            }
            finally
            {
                (materials as IDisposable)?.Dispose();
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void B1FacilitiesIncludeOneCuratedGenWorldCampaignLightbox()
        {
            var assembly = typeof(StationDecorationLayer).Assembly;
            var materialType = assembly.GetType(
                "MetroReplay.Presentation.B1HeroMaterialLibrary",
                true);
            var builderType = assembly.GetType(
                "MetroReplay.Presentation.B1HeroFacilityBuilder",
                true);
            var materials = Activator.CreateInstance(
                materialType!,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null,
                null,
                null);
            var root = new GameObject("B1BrandPlacementTestRoot");
            try
            {
                var build = builderType!.GetMethod(
                    "Build",
                    BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
                Assert.That(build, Is.Not.Null);
                build!.Invoke(null, new[] { root.transform, Vector3.zero, 0f, materials });

                var campaign = root.transform.Find("GenWorldCampaignLightbox");
                Assert.That(campaign, Is.Not.Null);
                Assert.That(root.GetComponentsInChildren<Transform>(true),
                    Has.Exactly(1).Matches<Transform>(item =>
                        item.name == "GenWorldCampaignLightbox"));
                var artwork = campaign!.Find("GenWorldPerseusArtwork");
                Assert.That(artwork, Is.Not.Null);
                Assert.That(artwork!.GetComponent<Renderer>().sharedMaterial.mainTexture, Is.Not.Null);
                Assert.That(root.GetComponentsInChildren<Collider>(true), Is.Empty);
            }
            finally
            {
                (materials as IDisposable)?.Dispose();
                UnityEngine.Object.DestroyImmediate(root);
            }
        }
    }
}
