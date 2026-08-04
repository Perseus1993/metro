using System;
using System.IO;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerSkinAtlas : IDisposable
    {
        public const int Columns = 2;
        public const int Rows = 2;
        public const int VariantCount = Columns * Rows;

        public Texture2D Texture { get; }

        private PassengerSkinAtlas(Texture2D texture)
        {
            Texture = texture;
        }

        public static PassengerSkinAtlas Load(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
                throw new FileNotFoundException("Passenger skin atlas was not found.", filePath);

            var texture = new Texture2D(2, 2, TextureFormat.RGBA32, false, false)
            {
                name = "CommuterSkinAtlasV1",
                filterMode = FilterMode.Bilinear,
                wrapMode = TextureWrapMode.Clamp
            };
            if (!texture.LoadImage(File.ReadAllBytes(filePath), true))
            {
                UnityEngine.Object.Destroy(texture);
                throw new InvalidOperationException("Passenger skin atlas is not a readable PNG image.");
            }
            return new PassengerSkinAtlas(texture);
        }

        public static int GetVariantIndex(int passengerId)
        {
            return (passengerId & int.MaxValue) % VariantCount;
        }

        public static Vector4 GetUvTransform(int variantIndex)
        {
            var normalized = ((variantIndex % VariantCount) + VariantCount) % VariantCount;
            var column = normalized % Columns;
            var row = normalized / Columns;
            return new Vector4(
                1f / Columns,
                1f / Rows,
                column / (float)Columns,
                row / (float)Rows);
        }

        public static Color GetJointColor(int variantIndex)
        {
            switch (((variantIndex % VariantCount) + VariantCount) % VariantCount)
            {
                case 0: return new Color(0.07f, 0.29f, 0.39f);
                case 1: return new Color(0.06f, 0.25f, 0.23f);
                case 2: return new Color(0.34f, 0.10f, 0.13f);
                default: return new Color(0.08f, 0.15f, 0.27f);
            }
        }

        public void Apply(
            Renderer[] renderers,
            int passengerId,
            MaterialPropertyBlock propertyBlock)
        {
            if (renderers == null)
                throw new ArgumentNullException(nameof(renderers));
            if (propertyBlock == null)
                throw new ArgumentNullException(nameof(propertyBlock));

            var skinIndex = GetVariantIndex(passengerId);
            var uvTransform = GetUvTransform(skinIndex);
            var jointColor = GetJointColor(skinIndex);
            foreach (var renderer in renderers)
            {
                if (renderer == null)
                    continue;
                var materials = renderer.sharedMaterials;
                for (var materialIndex = 0; materialIndex < materials.Length; materialIndex++)
                {
                    var material = materials[materialIndex];
                    var isJoint = material != null
                        && material.name.IndexOf("Joint", StringComparison.OrdinalIgnoreCase) >= 0;
                    propertyBlock.Clear();
                    propertyBlock.SetTexture("_MainTex", isJoint
                        ? Texture2D.whiteTexture
                        : Texture);
                    propertyBlock.SetTexture("baseColorTexture", isJoint
                        ? Texture2D.whiteTexture
                        : Texture);
                    propertyBlock.SetTexture("_BaseColorMap", isJoint
                        ? Texture2D.whiteTexture
                        : Texture);
                    propertyBlock.SetVector("_MainTex_ST", isJoint
                        ? new Vector4(1f, 1f, 0f, 0f)
                        : uvTransform);
                    propertyBlock.SetVector("baseColorTexture_ST", isJoint
                        ? new Vector4(1f, 1f, 0f, 0f)
                        : uvTransform);
                    propertyBlock.SetVector("_BaseColorMap_ST", isJoint
                        ? new Vector4(1f, 1f, 0f, 0f)
                        : uvTransform);
                    propertyBlock.SetVector("_SkinAtlasRect", isJoint
                        ? new Vector4(1f, 1f, 0f, 0f)
                        : uvTransform);
                    // The Quaternius animation library ships placeholder UVs where
                    // every vertex is (0, 1). Project the atlas across local X/Y so
                    // this prototype can still demonstrate clothing textures.
                    propertyBlock.SetFloat("_UsePlanarUV", isJoint ? 0f : 1f);
                    propertyBlock.SetVector(
                        "_PlanarUVTransform",
                        new Vector4(0.5f, 1f / 1.83f, 0.5f, 0f));
                    propertyBlock.SetColor("_Color", isJoint ? jointColor : Color.white);
                    propertyBlock.SetColor("baseColorFactor", isJoint ? jointColor : Color.white);
                    propertyBlock.SetColor("_BaseColor", isJoint ? jointColor : Color.white);
                    renderer.SetPropertyBlock(propertyBlock, materialIndex);
                }
            }
        }

        public void Dispose()
        {
            if (Texture != null)
                UnityEngine.Object.Destroy(Texture);
        }
    }
}
