using System.IO;
using MetroReplay.Application;
using MetroReplay.Infrastructure;
using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class ElevatorReplayPresenterTests
    {
        [Test]
        public void SamplesBoardingTravelAndArrivalAtAnySeekTime()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson());
            var sampler = new ElevatorReplaySampler(data, "elevator:test");

            Assert.That(sampler.HasEvents, Is.True);
            Assert.That(sampler.TrySample(2f, out var boarding), Is.True);
            Assert.That(boarding.Phase, Is.EqualTo(ElevatorVisualPhase.Boarding));
            Assert.That(boarding.AnchorPosition.y, Is.EqualTo(-5.85f).Within(0.001f));

            Assert.That(sampler.TrySample(5f, out var traveling), Is.True);
            Assert.That(traveling.Phase, Is.EqualTo(ElevatorVisualPhase.Traveling));
            Assert.That(traveling.TravelProgress, Is.EqualTo(0.5f).Within(0.001f));
            Assert.That(traveling.AnchorPosition.y, Is.EqualTo(-9.85f).Within(0.001f));

            Assert.That(sampler.TrySample(8f, out var arrived), Is.True);
            Assert.That(arrived.Phase, Is.EqualTo(ElevatorVisualPhase.Arrived));
            Assert.That(arrived.AnchorPosition.y, Is.EqualTo(-13.85f).Within(0.001f));

            sampler.TrySample(1f, out _);
            sampler.TrySample(5f, out var repeated);
            Assert.That(
                Vector3.Distance(traveling.AnchorPosition, repeated.AnchorPosition),
                Is.LessThan(0.0001f));
        }

        [Test]
        public void MovesTheBuiltCabinWithTheReplayClock()
        {
            var data = ReplayContractReader.Read(ReplayTestData.ValidJson());
            var root = new GameObject("ElevatorPresenterTest");
            try
            {
                new StationSceneBuilder(root.transform).Build(data);
                var car = root.transform.Find("elevator:test/ElevatorCar");
                Assert.That(car, Is.Not.Null);
                Assert.That(car!.Find("ElevatorCabin"), Is.Not.Null);
                Assert.That(car.Find("CabinFrontGlass"), Is.Not.Null);

                var presenter = new ElevatorReplayPresenter(root.transform, data);
                Assert.That(presenter.ElevatorCount, Is.EqualTo(1));

                presenter.Sync(2f);
                var boardingY = car.position.y;
                presenter.Sync(5f);
                var travelingY = car.position.y;
                presenter.Sync(8f);
                var arrivalY = car.position.y;

                Assert.That(boardingY, Is.EqualTo(-5.85f).Within(0.001f));
                Assert.That(travelingY, Is.EqualTo(-9.85f).Within(0.001f));
                Assert.That(arrivalY, Is.EqualTo(-13.85f).Within(0.001f));
                Assert.That(car.Find("ElevatorCabin")!.position.y,
                    Is.EqualTo(arrivalY + 1.18f).Within(0.001f));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void PackagedElevatorReturnsEmptyForItsNextPassengerTrip()
        {
            var path = Path.Combine(UnityEngine.Application.streamingAssetsPath, "replay.json");
            var data = ReplayContractReader.Read(File.ReadAllText(path));
            var sampler = new ElevatorReplaySampler(data, "element:elevator_a");

            Assert.That(sampler.HasEvents, Is.True);
            sampler.TrySample(35f, out var firstBoarding);
            sampler.TrySample(52.5f, out var firstTravel);
            sampler.TrySample(70f, out var firstArrival);
            sampler.TrySample(100f, out var emptyReturn);
            sampler.TrySample(123f, out var secondBoarding);

            Assert.That(firstBoarding.Phase, Is.EqualTo(ElevatorVisualPhase.Boarding));
            Assert.That(firstBoarding.AnchorPosition.y, Is.EqualTo(-13.85f).Within(0.001f));
            Assert.That(firstTravel.Phase, Is.EqualTo(ElevatorVisualPhase.Traveling));
            Assert.That(firstTravel.AnchorPosition.y, Is.EqualTo(-9.85f).Within(0.001f));
            Assert.That(firstArrival.AnchorPosition.y, Is.EqualTo(-5.85f).Within(0.001f));
            Assert.That(emptyReturn.Phase, Is.EqualTo(ElevatorVisualPhase.Repositioning));
            Assert.That(emptyReturn.AnchorPosition.y, Is.LessThan(-5.85f));
            Assert.That(emptyReturn.AnchorPosition.y, Is.GreaterThan(-13.85f));
            Assert.That(secondBoarding.Phase, Is.EqualTo(ElevatorVisualPhase.Boarding));
            Assert.That(secondBoarding.AnchorPosition.y, Is.EqualTo(-13.85f).Within(0.001f));
        }
    }
}
