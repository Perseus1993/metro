using MetroReplay.Application;
using NUnit.Framework;

namespace MetroReplay.Tests
{
    public sealed class ReplayClockTests
    {
        [Test]
        public void SupportsPlayPauseSpeedAndRandomSeek()
        {
            var clock = new ReplayClock(100f);
            clock.Seek(80f);
            Assert.That(clock.Time, Is.EqualTo(80f));
            clock.SetSpeed(4f);
            clock.Play();
            clock.Tick(2f);
            Assert.That(clock.Time, Is.EqualTo(88f));
            clock.Pause();
            clock.Tick(3f);
            Assert.That(clock.Time, Is.EqualTo(88f));
            clock.Seek(-20f);
            Assert.That(clock.Time, Is.EqualTo(0f));
            clock.Seek(200f);
            Assert.That(clock.Time, Is.EqualTo(100f));
        }
    }
}

