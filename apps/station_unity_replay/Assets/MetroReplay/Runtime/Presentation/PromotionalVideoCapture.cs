using UnityEngine;

namespace MetroReplay.Presentation
{
    public static class PromotionalVideoCapture
    {
        public const string ActivePreferenceKey = "MetroReplay.PromotionalVideoCapture.Active";
        public const string PortraitPreferenceKey = "MetroReplay.PromotionalVideoCapture.Portrait";
        public const float DurationSeconds = 26f;
        public const float RequestedPostIntroSeconds = 20f;
        public const float BackgroundMusicStartSeconds = 17f;
        public const float BackgroundMusicPeakVolume = 0.18f;
        public const float BackgroundMusicFadeInSeconds = 1.5f;
        public const float BackgroundMusicFadeOutSeconds = 2f;
        public const int LandscapeOutputWidth = 1920;
        public const int LandscapeOutputHeight = 1080;
        public const int PortraitOutputWidth = 1080;
        public const int PortraitOutputHeight = 1920;
        public const int FrameRate = 60;

        public static bool IsActive => PlayerPrefs.GetInt(ActivePreferenceKey, 0) == 1;
        public static bool IsPortrait => PlayerPrefs.GetInt(PortraitPreferenceKey, 0) == 1;
        public static int OutputWidth => IsPortrait ? PortraitOutputWidth : LandscapeOutputWidth;
        public static int OutputHeight => IsPortrait ? PortraitOutputHeight : LandscapeOutputHeight;

        public static void SetActive(bool active, bool portrait = false)
        {
            if (active)
            {
                PlayerPrefs.SetInt(ActivePreferenceKey, 1);
                if (portrait)
                    PlayerPrefs.SetInt(PortraitPreferenceKey, 1);
                else
                    PlayerPrefs.DeleteKey(PortraitPreferenceKey);
            }
            else
            {
                PlayerPrefs.DeleteKey(ActivePreferenceKey);
                PlayerPrefs.DeleteKey(PortraitPreferenceKey);
            }
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
