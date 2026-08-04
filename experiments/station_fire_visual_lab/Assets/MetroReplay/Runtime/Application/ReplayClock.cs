using UnityEngine;

namespace MetroReplay.Application
{
    public sealed class ReplayClock
    {
        public float Duration { get; }
        public float Time { get; private set; }
        public float Speed { get; private set; } = 1f;
        public bool IsPlaying { get; private set; }

        public ReplayClock(float duration)
        {
            Duration = Mathf.Max(0f, duration);
        }

        public void Play()
        {
            if (Duration <= 0f)
                return;
            if (Time >= Duration)
                Time = 0f;
            IsPlaying = true;
        }

        public void Pause()
        {
            IsPlaying = false;
        }

        public void Toggle()
        {
            if (IsPlaying)
                Pause();
            else
                Play();
        }

        public void SetSpeed(float speed)
        {
            Speed = Mathf.Clamp(speed, 0.1f, 32f);
        }

        public void Seek(float time)
        {
            Time = Mathf.Clamp(time, 0f, Duration);
        }

        public void Tick(float unscaledDeltaTime)
        {
            if (!IsPlaying)
                return;
            Time = Mathf.Min(Duration, Time + Mathf.Max(0f, unscaledDeltaTime) * Speed);
            if (Time >= Duration)
                IsPlaying = false;
        }
    }
}

