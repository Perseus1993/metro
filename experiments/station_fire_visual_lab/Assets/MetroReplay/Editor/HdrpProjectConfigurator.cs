using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace MetroReplay.Editor
{
    public static class HdrpProjectConfigurator
    {
        private const string AssetFolder = "Assets/MetroReplay/Settings";
        private const string AssetPath = AssetFolder + "/MetroReplayHDRP.asset";

        [MenuItem("Metro Replay/Configure HDRP")]
        public static void Configure()
        {
            EnsureConfigured();
            AssetDatabase.SaveAssets();
            Debug.Log("METRO_REPLAY_HDRP_CONFIGURED=" + AssetPath);
        }

        public static void EnsureConfigured()
        {
            if (!Directory.Exists(AssetFolder))
                Directory.CreateDirectory(AssetFolder);

            var asset = AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>(AssetPath);
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<HDRenderPipelineAsset>();
                asset.name = "Metro Replay HDRP";
                AssetDatabase.CreateAsset(asset, AssetPath);
            }

            var settings = asset.currentPlatformRenderPipelineSettings;
            settings.supportSSAO = true;
            settings.supportSSGI = true;
            settings.supportSSR = true;
            settings.supportSSRTransparent = true;
            settings.supportMotionVectors = true;
            settings.supportVolumetrics = true;
            settings.supportRayTracing = false;
            settings.hdShadowInitParams.supportScreenSpaceShadows = true;
            asset.currentPlatformRenderPipelineSettings = settings;

            GraphicsSettings.defaultRenderPipeline = asset;
            var currentQuality = QualitySettings.GetQualityLevel();
            for (var quality = 0; quality < QualitySettings.names.Length; quality++)
            {
                QualitySettings.SetQualityLevel(quality, false);
                QualitySettings.renderPipeline = asset;
            }
            QualitySettings.SetQualityLevel(currentQuality, true);
            PlayerSettings.colorSpace = ColorSpace.Linear;
            EditorUtility.SetDirty(asset);
        }
    }
}
