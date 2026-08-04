using System.Collections.Generic;
using MetroReplay.Application;
using MetroReplay.Domain;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class TrainReplaySamplerTests
    {
        [Test]
        public void SamplesApproachDwellDoorsAndDepartureFromSnapshots()
        {
            var sampler = new TrainReplaySampler(BuildReplay());

            Assert.That(sampler.TrySample(65f, out var approaching), Is.True);
            Assert.That(approaching.Phase, Is.EqualTo(TrainVisualPhase.Approaching));
            Assert.That(approaching.Visible, Is.True);
            Assert.That(approaching.NormalizedTravel, Is.LessThan(0f));

            Assert.That(sampler.TrySample(77f, out var dwelling), Is.True);
            Assert.That(dwelling.Phase, Is.EqualTo(TrainVisualPhase.Dwelling));
            Assert.That(dwelling.DoorOpenProgress, Is.EqualTo(1f).Within(0.001f));

            Assert.That(sampler.TrySample(89.5f, out var closing), Is.True);
            Assert.That(closing.Phase, Is.EqualTo(TrainVisualPhase.Dwelling));
            Assert.That(closing.DoorOpenProgress, Is.LessThan(0.5f));

            Assert.That(sampler.TrySample(92f, out var departing), Is.True);
            Assert.That(departing.Phase, Is.EqualTo(TrainVisualPhase.Departing));
            Assert.That(departing.NormalizedTravel, Is.GreaterThan(0f));
        }

        [Test]
        public void RandomSeekReturnsTheSameVisualSample()
        {
            var sampler = new TrainReplaySampler(BuildReplay());

            sampler.TrySample(81f, out var first);
            sampler.TrySample(25f, out _);
            sampler.TrySample(81f, out var second);

            Assert.That(second.Phase, Is.EqualTo(first.Phase));
            Assert.That(second.NormalizedTravel, Is.EqualTo(first.NormalizedTravel).Within(0.0001f));
            Assert.That(second.DoorOpenProgress, Is.EqualTo(first.DoorOpenProgress).Within(0.0001f));
        }

        [Test]
        public void SamplesImmediatePresentationLoopForInactiveReplay()
        {
            var sampler = new TrainReplaySampler(BuildReplay(includeServiceSegment: false));

            Assert.That(sampler.HasAuthoritativeMotion, Is.False);
            Assert.That(sampler.TrySamplePresentationLoop(0f, out var approachStart), Is.True);
            Assert.That(approachStart.Phase, Is.EqualTo(TrainVisualPhase.Approaching));
            Assert.That(approachStart.Visible, Is.True);
            Assert.That(approachStart.NormalizedTravel, Is.EqualTo(-1f).Within(0.001f));

            sampler.TrySamplePresentationLoop(7.5f, out var approachMiddle);
            Assert.That(approachMiddle.Phase, Is.EqualTo(TrainVisualPhase.Approaching));
            Assert.That(approachMiddle.NormalizedTravel, Is.EqualTo(-0.5f).Within(0.001f));

            sampler.TrySamplePresentationLoop(18f, out var dwelling);
            Assert.That(dwelling.Phase, Is.EqualTo(TrainVisualPhase.Dwelling));
            Assert.That(dwelling.DoorOpenProgress, Is.EqualTo(1f).Within(0.001f));

            sampler.TrySamplePresentationLoop(30f, out var departing);
            Assert.That(departing.Phase, Is.EqualTo(TrainVisualPhase.Departing));
            Assert.That(departing.NormalizedTravel, Is.GreaterThan(0f));

            sampler.TrySamplePresentationLoop(40f, out var hidden);
            Assert.That(hidden.Phase, Is.EqualTo(TrainVisualPhase.Hidden));
            Assert.That(hidden.Visible, Is.False);

            sampler.TrySamplePresentationLoop(7.5f, out var repeated);
            Assert.That(
                repeated.NormalizedTravel,
                Is.EqualTo(approachMiddle.NormalizedTravel).Within(0.0001f));
        }

        private static ReplayData BuildReplay(bool includeServiceSegment = true)
        {
            var level = new ReplayLevel(
                "b2",
                "B2",
                -14f,
                new[]
                {
                    new Vector2(0f, 0f),
                    new Vector2(80f, 0f),
                    new Vector2(80f, 20f),
                    new Vector2(0f, 20f)
                });
            var frames = includeServiceSegment
                ? new[]
                {
                    Frame(0f, Train("away", nextArrival: 75f)),
                    Frame(60f, Train("away", nextArrival: 75f)),
                    Frame(75f, Train("boarding", nextArrival: 75f)),
                    Frame(85f, Train("boarding", nextArrival: 75f)),
                    Frame(90f, Train("away", nextArrival: 150f, departureElapsed: 0f, departed: 1)),
                    Frame(105f, Train("away", nextArrival: 150f, departureElapsed: 15f, departed: 1))
                }
                : new[]
                {
                    Frame(0f, Train("away", nextArrival: 75f)),
                    Frame(45f, Train("away", nextArrival: 75f))
                };
            return new ReplayData(
                "train-test",
                new[] { level },
                new ReplayEntity[0],
                frames,
                new FacilityServiceEvent[0],
                ReplayClearanceAudit.Unavailable);
        }

        private static ReplayFrame Frame(float time, TrainSnapshot train)
        {
            return new ReplayFrame(
                time,
                new Dictionary<int, PassengerSnapshot>(),
                new Dictionary<int, TrainSnapshot> { [train.Id] = train });
        }

        private static TrainSnapshot Train(
            string state,
            float nextArrival,
            float? departureElapsed = null,
            int departed = 0)
        {
            return new TrainSnapshot(
                26,
                "default",
                "down",
                "platform:default:down",
                state,
                0,
                0,
                departureElapsed,
                departed,
                0,
                nextArrival,
                false,
                1200);
        }
    }
}
