using System;
using GLTFast;
using GLTFast.Logging;
using GLTFast.Materials;
using UnityEngine;
using MaterialBase = GLTFast.Schema.MaterialBase;

namespace MetroReplay.Presentation
{
    internal sealed class ReplayGltfMaterialGenerator : IMaterialGenerator
    {
        private Material _defaultMaterial;

        public Material GetDefaultMaterial(bool pointsSupport = false)
        {
            return _defaultMaterial ??= CreateMaterial("ReplayGltf_Default", Color.white);
        }

        public Material GenerateMaterial(
            MaterialBase gltfMaterial,
            IGltfReadable gltf,
            bool pointsSupport = false)
        {
            var pbr = gltfMaterial?.PbrMetallicRoughness;
            var material = CreateMaterial(
                gltfMaterial?.name ?? "ReplayGltf_Material",
                pbr?.BaseColor ?? Color.white);
            var textureInfo = pbr?.BaseColorTexture;
            if (textureInfo == null || textureInfo.index < 0)
                return material;

            var texture = gltf.GetTexture(textureInfo.index);
            if (texture == null)
                return material;
            material.SetTexture("_MainTex", texture);
            material.SetTexture("_BaseColorMap", texture);
            if (gltf.IsTextureYFlipped(textureInfo.index))
            {
                material.mainTextureScale = new Vector2(1f, -1f);
                material.mainTextureOffset = new Vector2(0f, 1f);
            }
            return material;
        }

        public void SetLogger(ICodeLogger logger)
        {
        }

        private static Material CreateMaterial(string name, Color color)
        {
            var shader = Shader.Find("HDRP/Lit");
            if (shader == null)
                throw new InvalidOperationException("HDRP/Lit shader is unavailable for glTF materials.");
            var material = new Material(shader) { name = name };
            material.SetColor("_Color", color);
            material.SetColor("_BaseColor", color);
            material.SetFloat("_Metallic", 0.03f);
            material.SetFloat("_Smoothness", 0.42f);
            return material;
        }
    }
}
