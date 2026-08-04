using MetroReplay.Presentation;
using NUnit.Framework;
using UnityEngine;

namespace MetroReplay.Tests
{
    public sealed class OpeningCameraStorySamplerTests
    {
        private const float MatchCutDistance = 0.69f;
        private static readonly Vector3 ArtworkTarget = new Vector3(2.23f, -4.4f, -11.91f);
        private static readonly Vector3 BillboardTarget = new Vector3(3f, -4.5f, -12f);
        private static readonly CameraOrbitView Destination = new CameraOrbitView(
            new Vector3(9.5f, -4.1f, -0.8f),
            13.8f,
            165f,
            3.5f);
        private static readonly CameraOrbitView TrainDestination = new CameraOrbitView(
            new Vector3(39f, -12.65f, -3f),
            12.8f,
            8f,
            5f);
        private static readonly CameraOrbitView OverviewDestination = new CameraOrbitView(
            new Vector3(39f, -10f, -12f),
            72f,
            152f,
            6f);

        [Test]
        public void StoryStartsCloseToTheB1Billboard()
        {
            var sample = OpeningCameraStorySampler.Sample(
                0f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(sample.Beat, Is.EqualTo(OpeningCameraStoryBeat.Billboard));
            Assert.That(sample.View.Target, Is.EqualTo(ArtworkTarget));
            Assert.That(sample.View.Distance, Is.EqualTo(MatchCutDistance).Within(0.001f));
            Assert.That(sample.View.Yaw, Is.EqualTo(180f).Within(0.001f));
            Assert.That(sample.View.Pitch, Is.Zero.Within(0.001f));
        }

        [Test]
        public void MatchCutHoldsStillWhileTheIntroOverlayDissolves()
        {
            var sample = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.MatchCutHoldEnd * 0.75f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(sample.View.Target, Is.EqualTo(ArtworkTarget));
            Assert.That(sample.View.Distance, Is.EqualTo(MatchCutDistance).Within(0.001f));
        }

        [Test]
        public void StoryPullsBackBeforeRevealingTheConcourse()
        {
            var close = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.BillboardHoldEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);
            var notice = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.DepartureNoticeEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);
            var reveal = OpeningCameraStorySampler.Sample(
                6.5f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(close.Beat, Is.EqualTo(OpeningCameraStoryBeat.DepartureNotice));
            Assert.That(notice.Beat, Is.EqualTo(OpeningCameraStoryBeat.ConcourseReveal));
            Assert.That(notice.View.Distance, Is.GreaterThan(close.View.Distance));
            Assert.That(reveal.View.Distance, Is.GreaterThan(notice.View.Distance));
            Assert.That(Vector3.Distance(reveal.View.Target, Destination.Target),
                Is.LessThan(Vector3.Distance(notice.View.Target, Destination.Target)));
        }

        [Test]
        public void StoryReachesTheExistingExhibitionViewBeforeTheTrainCut()
        {
            var sample = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.ConcourseRevealEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(sample.Beat, Is.EqualTo(OpeningCameraStoryBeat.ConcourseReveal));
            Assert.That(sample.View.Target, Is.EqualTo(Destination.Target));
            Assert.That(sample.View.Distance, Is.EqualTo(Destination.Distance).Within(0.001f));
            Assert.That(sample.View.Yaw, Is.EqualTo(Destination.Yaw).Within(0.001f));
            Assert.That(sample.View.Pitch, Is.EqualTo(Destination.Pitch).Within(0.001f));
        }

        [Test]
        public void TrainShotIsHeldForExactlyFiveSeconds()
        {
            var firstTrainFrame = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.ConcourseRevealEnd + 0.001f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);
            var lastTrainFrame = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.TrainHoldEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(OpeningCameraStorySampler.TrainHoldDuration, Is.EqualTo(5f));
            Assert.That(firstTrainFrame.Beat, Is.EqualTo(OpeningCameraStoryBeat.Train));
            Assert.That(lastTrainFrame.Beat, Is.EqualTo(OpeningCameraStoryBeat.Train));
            Assert.That(firstTrainFrame.View.Target, Is.EqualTo(TrainDestination.Target));
            Assert.That(lastTrainFrame.View.Target, Is.EqualTo(TrainDestination.Target));
        }

        [Test]
        public void StoryMovesFromTheTrainToTheTwoLevelOverview()
        {
            var transitioning = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.TrainHoldEnd
                + OpeningCameraStorySampler.OverviewTransitionDuration * 0.5f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);
            var complete = OpeningCameraStorySampler.Sample(
                OpeningCameraStorySampler.Duration + 10f,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination);

            Assert.That(transitioning.Beat, Is.EqualTo(OpeningCameraStoryBeat.Overview));
            Assert.That(transitioning.View.Distance, Is.GreaterThan(TrainDestination.Distance));
            Assert.That(transitioning.View.Distance, Is.LessThan(OverviewDestination.Distance));
            Assert.That(complete.Beat, Is.EqualTo(OpeningCameraStoryBeat.Complete));
            Assert.That(complete.View.Target, Is.EqualTo(OverviewDestination.Target));
            Assert.That(complete.View.Distance, Is.EqualTo(OverviewDestination.Distance).Within(0.001f));
        }

        [Test]
        public void OverviewViewFramesTheWholeStationBounds()
        {
            var bounds = new Bounds(
                new Vector3(39f, -10f, -12f),
                new Vector3(80f, 9f, 28f));

            var overview = OpeningCameraStorySampler.CreateOverviewView(bounds);

            Assert.That(overview.Target, Is.EqualTo(bounds.center));
            Assert.That(overview.Distance, Is.GreaterThan(bounds.extents.x));
            Assert.That(overview.Yaw, Is.EqualTo(152f));
            Assert.That(overview.Pitch, Is.EqualTo(6f));
        }

        [Test]
        public void PortraitStoryScansTheStationNativelyFromLeftToRight()
        {
            var bounds = new Bounds(
                new Vector3(39f, -10f, -12f),
                new Vector3(80f, 9f, 28f));
            OpeningCameraStorySampler.CreatePortraitPanoramaScanViews(
                bounds,
                out var panoramaStart,
                out var panoramaEnd);

            var arrived = OpeningCameraStorySampler.SamplePortrait(
                OpeningCameraStorySampler.PortraitOverviewArrivalEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                panoramaStart,
                panoramaEnd);
            var complete = OpeningCameraStorySampler.SamplePortrait(
                OpeningCameraStorySampler.PortraitDuration,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                panoramaStart,
                panoramaEnd);

            Assert.That(arrived.View.Target, Is.EqualTo(panoramaStart.Target));
            Assert.That(complete.View.Target, Is.EqualTo(panoramaEnd.Target));
            Assert.That(complete.View.Target.x, Is.GreaterThan(arrived.View.Target.x));
            Assert.That(complete.Beat, Is.EqualTo(OpeningCameraStoryBeat.Complete));
            Assert.That(panoramaStart.Distance, Is.LessThan(bounds.size.x));
            Assert.That(panoramaStart.Distance, Is.EqualTo(panoramaEnd.Distance));
        }

        [Test]
        public void PortraitStoryUsesWideFramingBeforeTheNarrowPanoramaScan()
        {
            var sample = OpeningCameraStorySampler.SamplePortrait(
                OpeningCameraStorySampler.BillboardHoldEnd,
                ArtworkTarget,
                BillboardTarget,
                MatchCutDistance,
                Destination,
                TrainDestination,
                OverviewDestination,
                OverviewDestination);

            Assert.That(sample.View.Distance,
                Is.EqualTo(OpeningCameraStorySampler.PortraitBillboardDistance).Within(0.001f));
            Assert.That(sample.Beat, Is.EqualTo(OpeningCameraStoryBeat.DepartureNotice));
        }

        [Test]
        public void FramedDistanceMatchesTheCapturedCoinViewportWidth()
        {
            const float verticalFieldOfView = 41.11f;
            const float viewportAspect = 16f / 9f;
            const float viewportWidth = 0.30f;
            var distance = OpeningCameraStorySampler.CalculateFramedDistance(
                1.42f,
                1.115f,
                verticalFieldOfView,
                viewportAspect,
                viewportWidth);
            var projectedWidth = 1.42f
                                 / (2f
                                    * distance
                                    * Mathf.Tan(verticalFieldOfView * 0.5f * Mathf.Deg2Rad)
                                    * viewportAspect);

            Assert.That(projectedWidth, Is.EqualTo(viewportWidth).Within(0.001f));
        }
    }
}
