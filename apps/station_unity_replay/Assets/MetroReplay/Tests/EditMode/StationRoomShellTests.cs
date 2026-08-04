using System.Linq;
using MetroReplay.Infrastructure;
using MetroReplay.Presentation;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class StationRoomShellTests
    {
        [Test]
        public void BuildsRoomBlockAsThinWallShellWithDoorAndCutawayRoof()
        {
            var root = new GameObject("RoomShellTestRoot");
            try
            {
                var data = ReplayContractReader.Read(RoomReplayJson());
                new StationSceneBuilder(root.transform).Build(data);

                var room = root.transform.Find("element:obstacle_service_center_test");
                Assert.That(room, Is.Not.Null);
                Assert.That(room.GetComponent<Renderer>(), Is.Null,
                    "The room root must not remain a solid opaque box.");
                Assert.That(room.childCount, Is.EqualTo(7));

                var expectedParts = new[]
                {
                    "Wall_Back",
                    "Wall_Left",
                    "Wall_Right",
                    "Wall_DoorLeft",
                    "Wall_DoorRight",
                    "Wall_DoorHeader",
                    "CutawayRoof"
                };
                foreach (var partName in expectedParts)
                    Assert.That(room.Find(partName), Is.Not.Null, partName);

                var doorLeft = room.Find("Wall_DoorLeft");
                var doorRight = room.Find("Wall_DoorRight");
                var openingWidth =
                    doorRight.localPosition.x - doorRight.localScale.x * 0.5f
                    - (doorLeft.localPosition.x + doorLeft.localScale.x * 0.5f);
                Assert.That(openingWidth, Is.GreaterThanOrEqualTo(1.19f));

                var opaqueWallParts = expectedParts
                    .Where(name => name.StartsWith("Wall_"))
                    .Select(name => room.Find(name));
                foreach (var part in opaqueWallParts)
                {
                    var horizontalThickness = Mathf.Min(
                        part.localScale.x,
                        part.localScale.z);
                    Assert.That(horizontalThickness, Is.LessThanOrEqualTo(0.121f));
                }

                var roofMaterial = room.Find("CutawayRoof")
                    .GetComponent<Renderer>().sharedMaterial;
                Assert.That(roofMaterial.GetFloat("_SurfaceType"), Is.EqualTo(1f));
                Assert.That(roofMaterial.GetColor("_BaseColor").a, Is.LessThanOrEqualTo(0.21f));
                Assert.That(roofMaterial.renderQueue, Is.GreaterThanOrEqualTo(3000));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        private static string RoomReplayJson()
        {
            var json = JObject.Parse(ReplayTestData.ValidJson(includeElevatorEvent: false));
            var scene = (JObject)json["replay_package"]!["station_scene"]!;
            var originalEntities = (JArray)scene["entities"]!;
            var floors = originalEntities.Take(2).Select(entity => entity.DeepClone()).ToArray();
            originalEntities.Clear();
            foreach (var floor in floors)
                originalEntities.Add(floor);
            originalEntities.Add(new JObject
            {
                ["entity_id"] = "element:obstacle_service_center_test",
                ["kind"] = "obstacle",
                ["label"] = "B1 service center room",
                ["geometry"] = new JObject
                {
                    ["shape"] = "polygon",
                    ["x_m"] = 5f,
                    ["y_m"] = 4f,
                    ["width_m"] = 0f,
                    ["height_m"] = 0f,
                    ["rotation_deg"] = 0f,
                    ["points_m"] = new JArray(
                        new JArray(2f, 2f),
                        new JArray(8f, 2f),
                        new JArray(8f, 6f),
                        new JArray(2f, 6f))
                },
                ["level_ids"] = new JArray("b1")
            });
            scene["runtime_bindings"] = new JArray();
            return json.ToString();
        }
    }
}
