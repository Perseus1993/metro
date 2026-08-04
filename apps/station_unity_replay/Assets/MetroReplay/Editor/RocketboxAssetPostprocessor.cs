using System;
using UnityEditor;

namespace MetroReplay.Editor
{
    internal sealed class RocketboxAssetPostprocessor : AssetPostprocessor
    {
        private const string AssetRoot = "Assets/Resources/PassengerBases/";

        private void OnPreprocessTexture()
        {
            if (!assetPath.StartsWith(AssetRoot, StringComparison.Ordinal))
                return;
            var importer = (TextureImporter)assetImporter;
            importer.maxTextureSize = 1024;
            importer.mipmapEnabled = true;
            importer.sRGBTexture = true;
            importer.textureCompression = TextureImporterCompression.CompressedHQ;
            importer.alphaSource = assetPath.IndexOf("opacity", StringComparison.OrdinalIgnoreCase) >= 0
                ? TextureImporterAlphaSource.FromGrayScale
                : TextureImporterAlphaSource.None;
        }

        private void OnPreprocessModel()
        {
            if (!assetPath.StartsWith(AssetRoot, StringComparison.Ordinal))
                return;
            var importer = (ModelImporter)assetImporter;
            importer.animationType = ModelImporterAnimationType.Human;
            importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            importer.importAnimation = assetPath.Contains("RocketboxAnimations");
            importer.importCameras = false;
            importer.importLights = false;
            importer.importBlendShapes = false;
            importer.isReadable = true;
            importer.importVisibility = false;
            importer.preserveHierarchy = true;
            importer.optimizeGameObjects = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;
        }

        private void OnPreprocessAnimation()
        {
            if (!assetPath.Contains("RocketboxAnimations"))
                return;
            var importer = (ModelImporter)assetImporter;
            var clips = importer.defaultClipAnimations;
            for (var index = 0; index < clips.Length; index++)
            {
                clips[index].name = ClipName(assetPath);
                clips[index].loopTime = true;
                clips[index].loopPose = true;
                clips[index].keepOriginalPositionXZ = true;
                clips[index].keepOriginalPositionY = true;
                clips[index].keepOriginalOrientation = true;
            }
            importer.clipAnimations = clips;
        }

        private static string ClipName(string path)
        {
            if (path.IndexOf("idle", StringComparison.OrdinalIgnoreCase) >= 0)
                return "Idle_Loop";
            if (path.IndexOf("run", StringComparison.OrdinalIgnoreCase) >= 0)
                return "Jog_Fwd_Loop";
            return "Walk_Loop";
        }
    }
}
