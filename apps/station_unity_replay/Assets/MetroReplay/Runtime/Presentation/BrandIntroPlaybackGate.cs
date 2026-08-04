using System;

namespace MetroReplay.Presentation
{
    /// <summary>
    /// Prevents the branded opening clock from advancing before the player is
    /// genuinely visible, and pauses it whenever the player loses focus.
    /// </summary>
    public sealed class BrandIntroPlaybackGate
    {
        private readonly int _requiredReadyFrames;
        private int _consecutiveReadyFrames;

        public BrandIntroPlaybackGate(int requiredReadyFrames)
        {
            if (requiredReadyFrames < 1)
                throw new ArgumentOutOfRangeException(nameof(requiredReadyFrames));

            _requiredReadyFrames = requiredReadyFrames;
        }

        public bool HasStarted { get; private set; }

        public bool ShouldAdvance(bool splashFinished, bool windowFocused)
        {
            if (HasStarted)
                return windowFocused;

            if (!splashFinished || !windowFocused)
            {
                _consecutiveReadyFrames = 0;
                return false;
            }

            _consecutiveReadyFrames++;
            if (_consecutiveReadyFrames < _requiredReadyFrames)
                return false;

            HasStarted = true;
            return true;
        }
    }
}
