using System.Collections.Generic;
using MetroReplay.Application;
using MetroReplay.Domain;
using MetroReplay.Infrastructure;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class ReplaySamplerTests
    {
        [Test]
        public void ReconstructsElevatorTravelAtAnySeekTime()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson());
            var sampler = new ReplaySampler(data);
            var poses = new List<PassengerPose>();

            sampler.Sample(5f, poses);
            var first = poses[0].Position;
            Assert.That(poses[0].InVerticalFacility, Is.True);
            Assert.That(first.y, Is.EqualTo(-9.85f).Within(0.01f));

            sampler.Sample(9f, poses);
            sampler.Sample(1f, poses);
            sampler.Sample(5f, poses);
            Assert.That(Vector3.Distance(first, poses[0].Position), Is.LessThan(0.0001f));
        }

        [Test]
        public void PlacesWalkingPassengerFeetOnWalkableSurface()
        {
            var data = ReplayContractReader.Read(
                ReplayTestData.ValidJson(includeElevatorEvent: false));
            var sampler = new ReplaySampler(data);
            var poses = new List<PassengerPose>();

            sampler.Sample(0f, poses);

            Assert.That(poses[0].Position.y, Is.EqualTo(-5.97f).Within(0.001f));
        }

        [Test]
        public void KeepsCapsuleFallbackBottomOnFootPosition()
        {
            var root = new GameObject("PassengerPoolTest");
            try
            {
                var pool = new Presentation.PassengerPool(root.transform, 1);
                var footPosition = new Vector3(0f, 2f, 0f);
                pool.Sync(new[]
                {
                    new PassengerPose(
                        1, footPosition, Vector3.forward, "b1", "walking", false)
                });

                var capsule = root.transform.GetChild(0).gameObject;
                Assert.That(
                    capsule.GetComponent<Renderer>().bounds.min.y,
                    Is.EqualTo(footPosition.y).Within(0.001f));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void SamplesThreeHundredPassengersWithoutDuplicateIds()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson(300));
            var sampler = new ReplaySampler(data);
            var poses = new List<PassengerPose>(300);

            sampler.Sample(5f, poses);

            Assert.That(poses.Count, Is.EqualTo(300));
            var ids = new HashSet<int>();
            foreach (var pose in poses)
                Assert.That(ids.Add(pose.Id), Is.True);
        }

        [TestCase("escalator", 30f)]
        [TestCase("stairs", 35f)]
        public void DerivedVerticalRoutePreservesAuthoritativeAnchorsAtReadableSlope(
            string kind,
            float expectedAngle)
        {
            var highAnchor = new Vector3(5f, -6f, -4f);
            var lowAnchor = new Vector3(5f, -14f, -7f);
            var route = VerticalFacilityRouteResolver.Resolve(kind, highAnchor, lowAnchor);

            Assert.That(Vector3.Distance(route.Sample(highAnchor, 0f), highAnchor),
                Is.LessThan(0.0001f));
            Assert.That(Vector3.Distance(route.Sample(highAnchor, 1f), lowAnchor),
                Is.LessThan(0.0001f));
            Assert.That(Vector3.Distance(route.Sample(lowAnchor, 0f), lowAnchor),
                Is.LessThan(0.0001f));
            Assert.That(Vector3.Distance(route.Sample(lowAnchor, 1f), highAnchor),
                Is.LessThan(0.0001f));

            foreach (var slope in new[]
            {
                route.Middle - route.LowAnchor,
                route.HighAnchor - route.Middle
            })
            {
                var horizontalRun = new Vector2(slope.x, slope.z).magnitude;
                var angle = Mathf.Atan2(Mathf.Abs(slope.y), horizontalRun) * Mathf.Rad2Deg;
                Assert.That(angle, Is.LessThanOrEqualTo(expectedAngle + 0.1f));
            }
        }

        [TestCase("queueing_exit_gate", false, "Idle_Loop")]
        [TestCase("running", false, "Jog_Fwd_Loop")]
        [TestCase("walking_to_vertical", false, "Walk_Loop")]
        [TestCase("riding_vertical", true, "Walk_Loop")]
        public void SelectsExistingQuaterniusAnimation(string state, bool vertical, string expected)
        {
            var pose = new PassengerPose(1, Vector3.zero, Vector3.forward, "b1", state, vertical);

            Assert.That(Presentation.PassengerPool.SelectAnimation(pose), Is.EqualTo(expected));
        }

        [Test]
        public void SelectsJogForEvacuatingPassengerMovingOnFloor()
        {
            var pose = new PassengerPose(
                1,
                Vector3.zero,
                Vector3.forward,
                "b1",
                "walking_to_exit_gate",
                false,
                "evacuate_station");

            Assert.That(
                Presentation.PassengerPool.SelectAnimation(pose),
                Is.EqualTo("Jog_Fwd_Loop"));
        }

        [Test]
        public void KeepsNormalPassengerWalkingAndVerticalEvacueeSafe()
        {
            var normal = new PassengerPose(
                1,
                Vector3.zero,
                Vector3.forward,
                "b1",
                "walking_to_exit_gate",
                false,
                "enter_and_board");
            var verticalEvacuee = new PassengerPose(
                2,
                Vector3.zero,
                Vector3.forward,
                "b1",
                "riding_vertical",
                true,
                "evacuate_station");

            Assert.That(
                Presentation.PassengerPool.SelectAnimation(normal),
                Is.EqualTo("Walk_Loop"));
            Assert.That(
                Presentation.PassengerPool.SelectAnimation(verticalEvacuee),
                Is.EqualTo("Walk_Loop"));
        }
    }
}
