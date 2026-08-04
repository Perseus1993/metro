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
        public void GeneratedLibraryContainsAllRocketboxCharactersWithThreeLevelLodPrefabs()
        {
            var guids = AssetDatabase.FindAssets(
                "t:Prefab",
                new[] { "Assets/Resources/PassengerBases/Generated/Prefabs" });
            Assert.That(guids.Length, Is.EqualTo(115));
            foreach (var guid in guids)
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(guid));
                Assert.That(prefab.GetComponent<PassengerBaseIdentity>(), Is.Not.Null);
                var animator = prefab.GetComponent<Animator>();
                Assert.That(animator, Is.Not.Null, prefab.name);
                Assert.That(animator.avatar, Is.Not.Null, prefab.name);
                Assert.That(animator.avatar.isHuman, Is.True, prefab.name);
                Assert.That(animator.runtimeAnimatorController, Is.Not.Null, prefab.name);
                var group = prefab.GetComponent<LODGroup>();
                Assert.That(group, Is.Not.Null, prefab.name);
                var lods = group.GetLODs();
                Assert.That(lods.Length, Is.EqualTo(3), prefab.name);
                Assert.That(
                    lods.SelectMany(level => level.renderers)
                        .All(renderer => renderer is SkinnedMeshRenderer skinned && skinned.sharedMesh != null),
                    Is.True,
                    prefab.name);
            }
        }

        [Test]
        public void FullLibraryIncludesAllFourNamedChildren()
        {
            var childIds = Resources.LoadAll<GameObject>("PassengerBases/Generated/Prefabs")
                .Select(prefab => prefab.GetComponent<PassengerBaseIdentity>()?.BaseId)
                .Where(id => id != null && id.Contains("_Child_"))
                .OrderBy(id => id)
                .ToArray();
            Assert.That(childIds, Is.EqualTo(new[]
            {
                "Female_Child_01", "Female_Child_02",
                "Male_Child_01", "Male_Child_02"
            }));
        }

        [Test]
        public void RuntimePassengerLibrarySeparatesOperationalRolesFromCommuters()
        {
            var library = RocketboxPassengerLibrary.Load();
            Assert.That(library.BaseCount, Is.EqualTo(61));
            Assert.That(library.SecurityBaseCount, Is.EqualTo(2));
            Assert.That(library.OperationsBaseCount, Is.EqualTo(52));
            Assert.That(
                library.Prototypes.Select(prefab => prefab.name),
                Has.None.StartsWith("Security_"));
            Assert.That(
                library.Prototypes.Select(prefab => prefab.name),
                Has.None.StartsWith("Fire_"));
            Assert.That(
                library.Prototypes.Select(prefab => prefab.name),
                Has.None.StartsWith("Medical_"));
            Assert.That(
                library.Prototypes.Select(prefab => prefab.name),
                Has.None.StartsWith("Police_"));
            Assert.That(
                library.SecurityPrototypes.Select(prefab => prefab.name).OrderBy(name => name),
                Is.EqualTo(new[] { "Security_Female_01", "Security_Male_01" }));
            Assert.That(
                library.OperationsPrototypes.Select(prefab => prefab.name),
                Has.Some.StartsWith("Fire_"));
            Assert.That(
                library.OperationsPrototypes.Select(prefab => prefab.name),
                Has.Some.StartsWith("Medical_"));
            Assert.That(
                library.OperationsPrototypes.Select(prefab => prefab.name),
                Has.Some.StartsWith("Police_"));
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
