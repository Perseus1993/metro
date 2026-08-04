using MetroReplay.Presentation;
using NUnit.Framework;

namespace MetroReplay.Tests
{
    public sealed class BrandIntroPlaybackGateTests
    {
        [Test]
        public void WaitsForConsecutiveVisibleFocusedFramesBeforeStarting()
        {
            var gate = new BrandIntroPlaybackGate(3);

            Assert.That(gate.ShouldAdvance(true, true), Is.False);
            Assert.That(gate.ShouldAdvance(true, true), Is.False);
            Assert.That(gate.HasStarted, Is.False);
            Assert.That(gate.ShouldAdvance(true, true), Is.True);
            Assert.That(gate.HasStarted, Is.True);
        }

        [Test]
        public void InterruptedReadinessRestartsTheWarmup()
        {
            var gate = new BrandIntroPlaybackGate(3);

            Assert.That(gate.ShouldAdvance(true, true), Is.False);
            Assert.That(gate.ShouldAdvance(true, false), Is.False);
            Assert.That(gate.ShouldAdvance(true, true), Is.False);
            Assert.That(gate.ShouldAdvance(true, true), Is.False);
            Assert.That(gate.ShouldAdvance(true, true), Is.True);
        }

        [Test]
        public void LosingFocusAfterStartPausesAndThenResumes()
        {
            var gate = new BrandIntroPlaybackGate(1);

            Assert.That(gate.ShouldAdvance(true, true), Is.True);
            Assert.That(gate.ShouldAdvance(true, false), Is.False);
            Assert.That(gate.HasStarted, Is.True);
            Assert.That(gate.ShouldAdvance(true, true), Is.True);
        }
    }
}
