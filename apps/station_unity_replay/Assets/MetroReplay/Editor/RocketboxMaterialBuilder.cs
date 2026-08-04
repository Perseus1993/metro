using System;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Editor
{
    internal static class RocketboxMaterialBuilder
    {
        public static Material[] Build(string baseName, string modelPath, Material[] sourceMaterials)
        {
            var result = new Material[sourceMaterials.Length];
            var textureFolder = Path.GetDirectoryName(Path.GetDirectoryName(modelPath))
                ?.Replace('\\', '/') + "/Textures";
            for (var index = 0; index < sourceMaterials.Length; index++)
                result[index] = BuildOne(baseName, textureFolder, sourceMaterials[index], index);
            return result;
        }

        private static Material BuildOne(
            string baseName,
            string textureFolder,
            Material source,
            int index)
        {
            var shader = Shader.Find("HDRP/Lit");
            if (shader == null)
                throw new InvalidOperationException("HDRP/Lit shader is unavailable.");
            var slotName = source != null ? source.name : $"slot_{index}";
            var assetPath = $"{RocketboxPassengerPrefabBuilder.MaterialFolder}/{baseName}_{slotName}.mat";
            AssetDatabase.DeleteAsset(assetPath);
            var material = new Material(shader) { name = $"{baseName}_{slotName}" };
            material.SetColor("_BaseColor", Color.white);
            material.SetFloat("_Metallic", 0f);
            material.SetFloat("_Smoothness", IsHead(slotName) ? 0.34f : 0.26f);
            var texture = FindColorTexture(textureFolder, slotName);
            if (texture != null)
                material.SetTexture("_BaseColorMap", texture);
            if (IsOpacity(slotName))
                ConfigureCutout(material);
            AssetDatabase.CreateAsset(material, assetPath);
            return material;
        }

        private static Texture2D FindColorTexture(string folder, string materialName)
        {
            var guids = AssetDatabase.FindAssets($"{materialName}_color t:Texture2D", new[] { folder });
            if (guids.Length == 0)
                guids = AssetDatabase.FindAssets("t:Texture2D", new[] { folder });
            foreach (var guid in guids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (path.IndexOf(materialName, StringComparison.OrdinalIgnoreCase) >= 0)
                    return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
            }
            return null;
        }

        private static void ConfigureCutout(Material material)
        {
            material.SetFloat("_AlphaCutoffEnable", 1f);
            material.SetFloat("_AlphaCutoff", 0.42f);
            material.SetFloat("_DoubleSidedEnable", 1f);
            material.EnableKeyword("_ALPHATEST_ON");
            material.renderQueue = (int)RenderQueue.AlphaTest;
        }

        private static bool IsHead(string name) =>
            name.IndexOf("head", StringComparison.OrdinalIgnoreCase) >= 0;

        private static bool IsOpacity(string name) =>
            name.IndexOf("opacity", StringComparison.OrdinalIgnoreCase) >= 0;
    }
}
