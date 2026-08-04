using MetroReplay.Presentation;
using NUnit.Framework;

namespace MetroReplay.Tests
{
    public sealed class PromotionalVideoCaptureTests
    {
        [Test]
        public void ExportPreset_CoversIntroAndApproximatelyTwentySecondsAfterward()
        {
            Assert.That(PromotionalVideoCapture.DurationSeconds, Is.EqualTo(26f));
            Assert.That(PromotionalVideoCapture.RequestedPostIntroSeconds, Is.EqualTo(20f));
            Assert.That(PromotionalVideoCapture.BackgroundMusicStartSeconds, Is.EqualTo(17f));
            Assert.That(PromotionalVideoCapture.BackgroundMusicPeakVolume, Is.EqualTo(0.18f));
            Assert.That(PromotionalVideoCapture.BackgroundMusicFadeInSeconds, Is.EqualTo(1.5f));
            Assert.That(PromotionalVideoCapture.BackgroundMusicFadeOutSeconds, Is.EqualTo(2f));
            Assert.That(PromotionalVideoCapture.OutputWidth, Is.EqualTo(1920));
            Assert.That(PromotionalVideoCapture.OutputHeight, Is.EqualTo(1080));
            Assert.That(PromotionalVideoCapture.FrameRate, Is.EqualTo(60));
        }

        [TestCase(-1f, 0f)]
        [TestCase(0f, 0f)]
        [TestCase(0.75f, 0.09f)]
        [TestCase(1.5f, 0.18f)]
        [TestCase(24f, 0.18f)]
        [TestCase(25f, 0.09f)]
        [TestCase(26f, 0f)]
        public void BackgroundMusicEnvelope_KeepsTheTrackLightAndFadesAtBothEnds(
            float elapsedSeconds,
            float expectedVolume)
        {
            Assert.That(
                PromotionalVideoCapture.EvaluateBackgroundMusicVolume(elapsedSeconds),
                Is.EqualTo(expectedVolume).Within(0.0001f));
        }
    }
}
