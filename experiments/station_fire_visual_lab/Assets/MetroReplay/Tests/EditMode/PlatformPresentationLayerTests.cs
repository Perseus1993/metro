using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using MetroReplay.Infrastructure;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class PlatformPresentationLayerTests
    {
        [Test]
        public void BuildsClosedLevelSlabsVisibleFromAboveAndBelow()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson());
            var root = new GameObject("ClosedLevelSlabTestRoot");
            try
            {
                new StationSceneBuilder(root.transform).Build(data);
                foreach (var levelId in new[] { "b1", "b2" })
                {
                    var level = root.transform.Find("Level_" + levelId);
                    Assert.That(level, Is.Not.Null);
                    var mesh = level!.GetComponent<MeshFilter>().sharedMesh;
                    Assert.That(mesh.vertexCount, Is.EqualTo(8));
                    Assert.That(mesh.triangles.Length, Is.EqualTo(36));
                    Assert.That(mesh.bounds.size.y, Is.EqualTo(0.18f).Within(0.001f));
                    Assert.That(level.GetComponentsInChildren<Collider>(true), Is.Empty);
                }
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void BuildsSixAlignedAnimatedScreenDoorModulesWithoutColliders()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidPlatformTrainJson());
            var root = new GameObject("PlatformPresentationTestRoot");
            IDisposable presentation = null;
            MetroTrainReplayPresenter train = null;
            try
            {
                new StationSceneBuilder(root.transform).Build(data);
                presentation = BuildPresentationLayer(root.transform, data);
                train = new MetroTrainReplayPresenter(root.transform, data);

                var modules = new List<Transform>();
                for (var index = 0; index < 6; index++)
                {
                    var module = root.transform.Find("platform_edge:test:" + (index + 1));
                    Assert.That(module, Is.Not.Null);
                    modules.Add(module!);
                }
                modules.Sort((left, right) => left.position.x.CompareTo(right.position.x));

                var trainLeaves = root.GetComponentsInChildren<Transform>(true)
                    .Where(item => item.name.StartsWith("AnimatedDoor_C", StringComparison.Ordinal))
                    .ToArray();
                Assert.That(trainLeaves.Length, Is.EqualTo(12));
                for (var index = 0; index < modules.Count; index++)
                {
                    var prefix = "AnimatedDoor_C" + (index + 1) + "_";
                    var pair = trainLeaves.Where(item => item.name.StartsWith(prefix, StringComparison.Ordinal)).ToArray();
                    Assert.That(pair.Length, Is.EqualTo(2));
                    var trainDoorCenterX = (pair[0].position.x + pair[1].position.x) * 0.5f;
                    var trainDoorCenterY = (pair[0].position.y + pair[1].position.y) * 0.5f;
                    var trainDoorCenterZ = (pair[0].position.z + pair[1].position.z) * 0.5f;
                    Assert.That(trainDoorCenterX, Is.EqualTo(modules[index].position.x).Within(0.03f));
                    Assert.That(Mathf.Abs(trainDoorCenterZ - modules[index].position.z),
                        Is.LessThan(0.35f),
                        "Train doors must remain in the front row beside the platform screen doors.");
                    var platformDoor = modules[index].Find("PlatformDoorLeaf_Left");
                    Assert.That(platformDoor, Is.Not.Null);
                    Assert.That(trainDoorCenterY, Is.EqualTo(platformDoor!.position.y).Within(0.03f),
                        "Train doors must align vertically with the platform screen doors.");
                }

                var screenLeaf = modules[0].Find("PlatformDoorLeaf_Left");
                Assert.That(screenLeaf, Is.Not.Null);
                var closed = screenLeaf!.localPosition;
                train.Sync(12f);
                Assert.That(Mathf.Abs(screenLeaf.localPosition.x - closed.x), Is.EqualTo(0.62f).Within(0.01f));

                var platformLayer = root.transform.Find("PlatformPresentationLayer");
                Assert.That(platformLayer, Is.Not.Null);
                Assert.That(platformLayer!.GetComponentsInChildren<Transform>(true)
                    .Count(item => item.name.StartsWith("PlatformQueueMarker_", StringComparison.Ordinal)),
                    Is.EqualTo(6));
                Assert.That(modules.SelectMany(item => item.GetComponentsInChildren<Collider>(true)), Is.Empty);
                Assert.That(platformLayer.GetComponentsInChildren<Collider>(true), Is.Empty);
            }
            finally
            {
                train?.Dispose();
                presentation?.Dispose();
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static IDisposable BuildPresentationLayer(Transform parent, MetroReplay.Domain.ReplayData data)
        {
            var assembly = typeof(StationSceneBuilder).Assembly;
            var type = assembly.GetType("MetroReplay.Presentation.PlatformPresentationLayer", true);
            var instance = Activator.CreateInstance(
                type!,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null,
                null,
                null);
            var build = type!.GetMethod(
                "Build",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            Assert.That(build, Is.Not.Null);
            var arguments = new object[] { parent, data, null };
            var built = (bool)build!.Invoke(instance, arguments)!;
            Assert.That(built, Is.True);
            return (IDisposable)instance!;
        }
    }
}
