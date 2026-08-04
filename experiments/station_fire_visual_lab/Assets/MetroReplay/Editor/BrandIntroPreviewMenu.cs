using MetroReplay.Presentation;
using UnityEditor;
using UnityEngine;

namespace MetroReplay.Editor
{
    internal static class BrandIntroPreviewMenu
    {
        private const string MenuRoot = "Metro Replay/Brand Intro/";

        [MenuItem(MenuRoot + "Hold Next Preview for 30 Seconds")]
        private static void ArmPreviewHold()
        {
            PlayerPrefs.SetInt(BrandIntroBootstrap.PreviewHoldPrefKey, 1);
            PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewLoopPrefKey);
            PlayerPrefs.Save();
            Debug.Log("The next Brand Intro preview will hold on the resolved logo for 30 seconds. Any input still skips it.");
        }

        [MenuItem(MenuRoot + "Loop Rotation Preview Until Stopped")]
        private static void ArmRotationLoop()
        {
            PlayerPrefs.SetInt(BrandIntroBootstrap.PreviewLoopPrefKey, 1);
            PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewHoldPrefKey);
            PlayerPrefs.Save();
            Debug.Log("The next Brand Intro preview will loop the coin rotation until Play Mode is stopped. This editor-only override is not included in builds.");
        }

        [MenuItem(MenuRoot + "Clear Preview Hold")]
        private static void ClearPreviewHold()
        {
            PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewHoldPrefKey);
            PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewLoopPrefKey);
            PlayerPrefs.Save();
            Debug.Log("Brand Intro preview hold cleared.");
        }
    }
}
