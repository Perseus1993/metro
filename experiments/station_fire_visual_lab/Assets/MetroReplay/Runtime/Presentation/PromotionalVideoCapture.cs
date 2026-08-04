using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class PromotionalVideoCapture
    {
        public const string ActivePreferenceKey = "MetroReplay.PromotionalVideoCapture.Active";
        public const float DurationSeconds = 26f;
        public const float RequestedPostIntroSeconds = 20f;
        public const float BackgroundMusicStartSeconds = 17f;
        public const float BackgroundMusicPeakVolume = 0.18f;
        public const float BackgroundMusicFadeInSeconds = 1.5f;
        public const float BackgroundMusicFadeOutSeconds = 2f;
        public const int OutputWidth = 1920;
        public const int OutputHeight = 1080;
        public const int FrameRate = 60;

        public static bool IsActive => PlayerPrefs.GetInt(ActivePreferenceKey, 0) == 1;

        public static void SetActive(bool active)
        {
            if (active)
                PlayerPrefs.SetInt(ActivePreferenceKey, 1);
            else
                PlayerPrefs.DeleteKey(ActivePreferenceKey);
            PlayerPrefs.Save();
        }

        public static float EvaluateBackgroundMusicVolume(float elapsedSeconds)
        {
            var fadeIn = Mathf.Clamp01(elapsedSeconds / BackgroundMusicFadeInSeconds);
            var fadeOut = Mathf.Clamp01(
                (DurationSeconds - elapsedSeconds) / BackgroundMusicFadeOutSeconds);
            return BackgroundMusicPeakVolume * Mathf.Min(fadeIn, fadeOut);
        }
    }
}
