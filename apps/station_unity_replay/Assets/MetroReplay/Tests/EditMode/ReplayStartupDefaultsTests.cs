using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using MetroReplay.Infrastructure;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class ReplayStartupDefaultsTests
    {
        [Test]
        public void DoubleClickDefaultsToFiftyPassengerClearance()
        {
            var arguments = new[] { "MetroStation3DReplay.exe" };
            Assert.That(InvokePrivate<float>("ResolveInitialTime", arguments), Is.Zero);
            Assert.That(InvokePrivate<bool>("ShouldUseClearanceHero", arguments), Is.True);
            Assert.That(InvokePrivate<bool>("ShouldUsePlatformHero", arguments), Is.False);
            Assert.That(InvokePrivate<bool>("ShouldShowTrain", arguments), Is.True);
            Assert.That(InvokePrivate<bool>("ShouldUseOpeningStory", arguments), Is.True);
        }

        [Test]
        public void ExplicitPresentationArgumentsOverrideClearanceDefaults()
        {
            var arguments = new[]
            {
                "MetroStation3DReplay.exe",
                "--start-time", "82",
                "--platform-hero",
                "--hide-train"
            };
            Assert.That(InvokePrivate<float>("ResolveInitialTime", arguments), Is.EqualTo(82f));
            Assert.That(InvokePrivate<bool>("ShouldUseClearanceHero", arguments), Is.False);
            Assert.That(InvokePrivate<bool>("ShouldUsePlatformHero", arguments), Is.True);
            Assert.That(InvokePrivate<bool>("ShouldShowTrain", arguments), Is.False);
        }

        [Test]
        public void AutomatedCapturesSkipTheInteractiveOpeningStory()
        {
            Assert.That(InvokePrivate<bool>(
                "ShouldUseOpeningStory",
                new[] { "MetroStation3DReplay.exe", "--screenshot-out", "capture.png" }),
                Is.False);
            Assert.That(InvokePrivate<bool>(
                "ShouldUseOpeningStory",
                new[] { "MetroStation3DReplay.exe", "--acceptance-out", "result.json" }),
                Is.False);
            Assert.That(InvokePrivate<bool>(
                "ShouldUseOpeningStory",
                new[] { "MetroStation3DReplay.exe", "--skip-opening-story" }),
                Is.False);
        }

        [Test]
        public void PackagedReplayIsCompleteHighFidelityFiftyPassengerClearance()
        {
            var path = Path.Combine(UnityEngine.Application.streamingAssetsPath, "replay.json");
            Assert.That(File.Exists(path), Is.True, "Packaged replay.json is missing.");
            var data = ReplayContractReader.Read(File.ReadAllText(path));

            Assert.That(data.ClearanceAudit.IsAvailable, Is.True);
            Assert.That(data.ClearanceAudit.Cleared, Is.True);
            Assert.That(data.ClearanceAudit.TotalPassengers, Is.EqualTo(50));
            Assert.That(data.ClearanceAudit.CompletedPassengers, Is.EqualTo(50));
            Assert.That(data.ClearanceAudit.RemainingPassengers, Is.Zero);
            Assert.That(data.ClearanceAudit.ClearanceTime, Is.EqualTo(253f));
            Assert.That(data.Frames[0].Passengers.Count, Is.EqualTo(50));
            Assert.That(data.FinalVisiblePassengers, Is.Zero);
            var extendedIntervals = 0;
            for (var index = 1; index < data.Frames.Count; index++)
            {
                var interval = data.Frames[index].Time - data.Frames[index - 1].Time;
                if (interval > 1.001f)
                    extendedIntervals++;
                Assert.That(
                    interval,
                    Is.LessThanOrEqualTo(2.001f),
                    "The default Unity replay must remain at one-second fidelity apart from the final clearance frame.");
            }
            Assert.That(extendedIntervals, Is.LessThanOrEqualTo(1));

            var root = new GameObject("ClearanceDefaultAssetsTest");
            MetroTrainReplayPresenter train = null;
            try
            {
                new StationSceneBuilder(root.transform).Build(data);
                BuildClearanceHero(root.transform, data);

                var elevator = root.transform.Find("element:elevator_a");
                Assert.That(elevator, Is.Not.Null);
                Assert.That(elevator!.GetComponentsInChildren<Renderer>(true), Is.Not.Empty);
                Assert.That(elevator.GetComponentsInChildren<Renderer>(true),
                    Has.All.Matches<Renderer>(renderer => renderer.enabled));
                var elevatorEntity = FindEntity(data, "element:elevator_a");
                var elevatorAnchor = data.ToWorld(
                    elevatorEntity.Geometry.Points[0].x,
                    elevatorEntity.Geometry.Points[0].y,
                    elevatorEntity.LevelIds[0],
                    0.15f);
                Assert.That(Vector3.Distance(elevator.position, elevatorAnchor), Is.LessThan(0.001f));
                var elevatorUpperAnchor = data.ToWorld(
                    elevatorEntity.Geometry.Points[elevatorEntity.Geometry.Points.Count - 1].x,
                    elevatorEntity.Geometry.Points[elevatorEntity.Geometry.Points.Count - 1].y,
                    elevatorEntity.LevelIds[elevatorEntity.LevelIds.Count - 1],
                    0.15f);
                Assert.That(elevatorUpperAnchor.x, Is.EqualTo(elevatorAnchor.x).Within(0.001f));
                Assert.That(elevatorUpperAnchor.z, Is.EqualTo(elevatorAnchor.z).Within(0.001f),
                    "Cross-level plans must be registered to the same physical elevator shaft.");
                Assert.That(root.transform.Find(
                    "B1HeroSample/ImportedStationAssets/ImportedVerticalTransport/AccessibleElevator_Complete"),
                    Is.Null, "The hero decoration layer must not create a second, non-authoritative elevator.");

                var heroRoot = root.transform.Find("B1HeroSample");
                Assert.That(heroRoot, Is.Not.Null);
                Assert.That(heroRoot!.Find("HeroEntryFareGates"), Is.Not.Null,
                    "The opposite entry side must receive the same finished fare-gate treatment.");
                Assert.That(heroRoot.Find("HeroExitFareGates"), Is.Not.Null,
                    "The exit side must keep its finished fare-gate treatment.");
                var heroFloor = heroRoot.Find("HeroFloor");
                Assert.That(heroFloor, Is.Not.Null);
                var b1Level = data.GetLevel("b1_concourse");
                var expectedWidth = b1Level.Footprint[1].x - b1Level.Footprint[0].x;
                Assert.That(heroFloor!.GetComponent<Renderer>().bounds.size.x,
                    Is.GreaterThanOrEqualTo(expectedWidth - 0.05f),
                    "The finished B1 shell must cover both concourse sides.");
                Assert.That(heroRoot.GetComponentsInChildren<Collider>(true), Is.Empty,
                    "Full-concourse decoration must remain presentation-only.");

                var oppositeServiceRoom = root.transform.Find("element:obstacle_service_center_left");
                Assert.That(oppositeServiceRoom, Is.Not.Null);
                Assert.That(oppositeServiceRoom!.GetComponentsInChildren<Renderer>(true),
                    Has.All.Matches<Renderer>(renderer => renderer.enabled),
                    "Opposite-side room finishes must not be hidden with the selected hero bay.");

                train = new MetroTrainReplayPresenter(root.transform, data, true);
                train.Sync(0f);
                Assert.That(train.IsVisible, Is.True);
                Assert.That(train.IsEnvironmentFallbackActive, Is.True);
                var trainRoot = root.transform.Find("MetroTrain_Replay");
                Assert.That(trainRoot, Is.Not.Null);
                var approachStart = trainRoot!.position;
                train.Sync(7.5f);
                Assert.That(train.IsVisible, Is.True);
                Assert.That(train.IsEnvironmentFallbackActive, Is.True);
                Assert.That(Vector3.Distance(approachStart, trainRoot.position),
                    Is.GreaterThan(10f),
                    "The presentation-only fallback train must visibly approach the platform.");
                train.Sync(15f);
                var trainBounds = CombinedBounds(trainRoot!.GetComponentsInChildren<Renderer>(true));
                foreach (var connectorId in new[]
                {
                    "element:down_escalator_a",
                    "element:down_escalator_b",
                    "element:up_escalator_a",
                    "element:up_escalator_b",
                    "element:stairs_a"
                })
                {
                    var connector = root.transform.Find(connectorId);
                    Assert.That(connector, Is.Not.Null);
                    var stepPrefix = connectorId.EndsWith("stairs_a", StringComparison.Ordinal)
                        ? "StairTread_"
                        : "EscalatorStep_";
                    var steps = connector!.GetComponentsInChildren<Transform>(true)
                        .Where(item => item.name.StartsWith(stepPrefix, StringComparison.Ordinal))
                        .ToArray();
                    Assert.That(steps.Length,
                        Is.GreaterThanOrEqualTo(40),
                        connectorId + " must contain continuous steps across the eight-metre rise.");
                    foreach (var renderer in connector!.GetComponentsInChildren<Renderer>(true))
                    {
                        Assert.That(renderer.bounds.Intersects(trainBounds), Is.False,
                            connectorId + " must stay outside the train clearance envelope.");
                    }
                }
            }
            finally
            {
                train?.Dispose();
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static MetroReplay.Domain.ReplayEntity FindEntity(
            MetroReplay.Domain.ReplayData data,
            string id)
        {
            foreach (var entity in data.Entities)
            {
                if (string.Equals(entity.Id, id, StringComparison.Ordinal))
                    return entity;
            }

            Assert.Fail("Replay entity is missing: " + id);
            return null!;
        }

        private static void BuildClearanceHero(Transform parent, MetroReplay.Domain.ReplayData data)
        {
            var type = typeof(StationSceneBuilder).Assembly.GetType(
                "MetroReplay.Presentation.B1HeroSceneBuilder",
                true);
            var instance = Activator.CreateInstance(
                type!,
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
                null,
                new object[] { parent, data, true },
                null);
            var build = type!.GetMethod(
                "Build",
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            Assert.That(build, Is.Not.Null);
            build!.Invoke(instance, null);
        }

        private static Bounds CombinedBounds(IReadOnlyList<Renderer> renderers)
        {
            Assert.That(renderers, Is.Not.Empty);
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Count; index++)
                bounds.Encapsulate(renderers[index].bounds);
            return bounds;
        }

        private static T InvokePrivate<T>(string name, IReadOnlyList<string> arguments)
        {
            var method = typeof(ReplayApplicationRoot).GetMethod(
                name,
                BindingFlags.Static | BindingFlags.NonPublic);
            Assert.That(method, Is.Not.Null);
            return (T)method!.Invoke(null, new object[] { arguments })!;
        }
    }
}
