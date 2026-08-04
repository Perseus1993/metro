using System.Linq;
using MetroReplay.Domain;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEditor;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class RocketboxPassengerAssetTests
    {
        [Test]
        public void GeneratedLibraryContainsEightThreeLevelLodPrefabs()
        {
            var guids = AssetDatabase.FindAssets(
                "t:Prefab",
                new[] { "Assets/Resources/PassengerBases/Generated/Prefabs" });
            Assert.That(guids.Length, Is.EqualTo(8));
            foreach (var guid in guids)
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(guid));
                Assert.That(prefab.GetComponent<PassengerBaseIdentity>(), Is.Not.Null);
                Assert.That(prefab.GetComponent<LODGroup>(), Is.Not.Null);
                Assert.That(prefab.GetComponent<LODGroup>().GetLODs().Length, Is.EqualTo(3));
            }
        }

        [Test]
        public void LodMeshesActuallyReduceVertexCount()
        {
            var prefab = Resources.LoadAll<GameObject>("PassengerBases/Generated/Prefabs").First();
            var lods = prefab.GetComponent<LODGroup>().GetLODs();
            var counts = lods.Select(level =>
                ((SkinnedMeshRenderer)level.renderers[0]).sharedMesh.vertexCount).ToArray();
            Assert.That(counts[1], Is.LessThan(counts[0]));
            Assert.That(counts[2], Is.LessThan(counts[1]));
        }

        [Test]
        public void RuntimePoolPlacesRocketboxFeetOnFootPosition()
        {
            var prefab = Resources.LoadAll<GameObject>(
                "PassengerBases/Generated/Prefabs").First();
            var root = new GameObject("RocketboxGroundingTest");
            try
            {
                var pool = new PassengerPool(root.transform, 0);
                pool.UsePrototype(prefab);
                var footPosition = new Vector3(0f, 2f, 0f);
                pool.Sync(new[]
                {
                    new PassengerPose(
                        1, footPosition, Vector3.forward, "b1", "walking", false)
                });

                var avatar = root.transform.GetChild(0).gameObject;
                var minimumRendererY = avatar.GetComponentsInChildren<Renderer>(true)
                    .Min(renderer => renderer.bounds.min.y);
                Assert.That(minimumRendererY, Is.EqualTo(footPosition.y).Within(0.03f));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }
    }
}
