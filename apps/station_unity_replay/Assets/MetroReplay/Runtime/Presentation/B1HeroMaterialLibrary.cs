using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class B1HeroMaterialLibrary : IDisposable
    {
        private const string ImportedTextureRoot =
            "MetroReplay/ThirdParty/SubwayTerminalPrototype/Textures/";
        private readonly List<UnityEngine.Object> _resources = new List<UnityEngine.Object>();

        public Material Floor { get; }
        public Material Wall { get; }
        public Material WallBlue { get; }
        public Material Ceiling { get; }
        public Material PerforatedPanel { get; }
        public Material DarkMetal { get; }
        public Material BrushedSteel { get; }
        public Material Sign { get; }
        public Material Glass { get; }
        public Material Light { get; }
        public Material GreenLight { get; }
        public Material BlueAccent { get; }
        public Material Tactile { get; }
        public Material EmergencyGreen { get; }
        public Material AdvertisingWhite { get; }
        public Material GenWorldPoster { get; }
        public Material Black { get; }
        public Material ImportedEscalator { get; }
        public Material ImportedTrim { get; }
        public Material SafetyRed { get; }

        public B1HeroMaterialLibrary()
        {
            Floor = CreateLit("B1 grey terrazzo", new Color(0.88f, 0.89f, 0.91f), 0.04f, 0.52f);
            if (!ApplyImportedSurface(
                    Floor,
                    "TX_Floor_Subway_01a_ALB",
                    "TX_Floor_Subway_01a_NRM",
                    new Vector2(9f, 6f)))
            {
                var tileTexture = CreateTerrazzoTexture();
                Floor.mainTexture = tileTexture;
                Floor.mainTextureScale = new Vector2(18f, 12f);
            }

            Wall = CreateLit("B1 warm white wall panel", new Color(0.90f, 0.92f, 0.94f), 0.04f, 0.48f);
            ApplyImportedSurface(
                Wall,
                "TX_Wall_Subway_01a_ALB",
                "TX_Wall_Subway_01a_NRM",
                new Vector2(5f, 2f));
            WallBlue = CreateLit("B1 Xi'an line blue panel", new Color(0.09f, 0.27f, 0.52f), 0.18f, 0.56f);
            Ceiling = CreateLit("B1 white aluminium ceiling", new Color(0.88f, 0.90f, 0.92f), 0.28f, 0.42f);
            ApplyImportedSurface(
                Ceiling,
                "TX_Ceiling_Subway_01a_ALB",
                "TX_Ceiling_Subway_01a_NRM",
                new Vector2(8f, 5f));
            PerforatedPanel = CreateLit("B1 perforated aluminium panel", new Color(0.70f, 0.73f, 0.76f), 0.34f, 0.38f);
            PerforatedPanel.mainTexture = CreatePerforatedTexture();
            PerforatedPanel.mainTextureScale = new Vector2(12f, 4f);
            DarkMetal = CreateLit("B1 dark metal", new Color(0.055f, 0.065f, 0.078f), 0.72f, 0.64f);
            BrushedSteel = CreateLit("B1 brushed steel", new Color(0.48f, 0.52f, 0.56f), 0.82f, 0.66f);
            Sign = CreateLit("B1 wayfinding charcoal", new Color(0.025f, 0.032f, 0.045f), 0.12f, 0.48f);
            Glass = CreateTransparent("B1 safety glass", new Color(0.38f, 0.56f, 0.62f, 0.17f), 0.80f);
            Light = CreateEmissive("B1 neutral white linear light", new Color(0.94f, 0.96f, 1f), 2.3f);
            GreenLight = CreateEmissive("B1 gate indicator", new Color(0.05f, 0.90f, 0.50f), 3.2f);
            BlueAccent = CreateEmissive("B1 line accent", new Color(0.05f, 0.34f, 0.72f), 0.85f);
            Tactile = CreateLit("B1 tactile paving", new Color(0.82f, 0.60f, 0.12f), 0.02f, 0.34f);
            EmergencyGreen = CreateEmissive("B1 emergency sign", new Color(0.02f, 0.52f, 0.24f), 1.9f);
            AdvertisingWhite = CreateEmissive("B1 information lightbox", new Color(0.64f, 0.72f, 0.80f), 0.80f);
            GenWorldPoster = CreateEmissive("B1 GenWorld campaign poster", Color.white, 0.55f);
            ApplyGenWorldPoster(GenWorldPoster);
            Black = CreateLit("B1 reveal and seam", new Color(0.012f, 0.016f, 0.021f), 0.30f, 0.26f);
            ImportedEscalator = CreateLit(
                "B1 imported escalator cladding", Color.white, 0.62f, 0.68f);
            ApplyImportedSurface(
                ImportedEscalator,
                "TX_Escalator_01a_ALB",
                "TX_Escalator_01a_NRM",
                Vector2.one);
            ImportedTrim = CreateLit("B1 imported trim", Color.white, 0.74f, 0.64f);
            ApplyImportedSurface(
                ImportedTrim,
                "TX_Trim_Subway_01a_ALB",
                "TX_Trim_Subway_01a_NRM",
                Vector2.one);
            SafetyRed = CreateLit("B1 fire safety red", new Color(0.68f, 0.035f, 0.025f), 0.18f, 0.48f);
        }

        public void Dispose()
        {
            foreach (var resource in _resources)
            {
                if (resource == null)
                    continue;
                if (UnityEngine.Application.isPlaying)
                    UnityEngine.Object.Destroy(resource);
                else
                    UnityEngine.Object.DestroyImmediate(resource);
            }
            _resources.Clear();
        }

        private static bool ApplyImportedSurface(
            Material material,
            string albedoName,
            string normalName,
            Vector2 tiling)
        {
            var albedo = Resources.Load<Texture2D>(ImportedTextureRoot + albedoName);
            if (albedo == null)
                return false;

            if (material.HasProperty("_BaseColorMap"))
            {
                material.SetTexture("_BaseColorMap", albedo);
                material.SetTextureScale("_BaseColorMap", tiling);
            }
            else
            {
                material.mainTexture = albedo;
                material.mainTextureScale = tiling;
            }

            var normal = Resources.Load<Texture2D>(ImportedTextureRoot + normalName);
            if (normal != null && material.HasProperty("_NormalMap"))
            {
                material.SetTexture("_NormalMap", normal);
                material.SetTextureScale("_NormalMap", tiling);
                material.EnableKeyword("_NORMALMAP_TANGENT_SPACE");
            }
            return true;
        }

        private static void ApplyGenWorldPoster(Material material)
        {
            var poster = Resources.Load<Texture2D>("BrandIntro/perseus-team");
            if (poster == null)
            {
                Debug.LogWarning("GenWorld campaign poster texture is unavailable.");
                return;
            }

            material.mainTexture = poster;
            material.mainTextureScale = Vector2.one;
            if (material.HasProperty("_BaseColorMap"))
                material.SetTexture("_BaseColorMap", poster);
            if (material.HasProperty("_EmissiveColorMap"))
            {
                material.SetTexture("_EmissiveColorMap", poster);
                material.EnableKeyword("_EMISSIVE_COLOR_MAP");
            }
        }

        private Material CreateLit(string name, Color color, float metallic, float smoothness)
        {
            var shader = Shader.Find("HDRP/Lit");
            if (shader == null)
                throw new InvalidOperationException("Unity lit shader is unavailable.");
            var material = new Material(shader) { name = name };
            material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Metallic"))
                material.SetFloat("_Metallic", metallic);
            if (material.HasProperty("_Glossiness"))
                material.SetFloat("_Glossiness", smoothness);
            if (material.HasProperty("_Smoothness"))
                material.SetFloat("_Smoothness", smoothness);
            _resources.Add(material);
            return material;
        }

        private Material CreateEmissive(string name, Color color, float intensity)
        {
            var material = CreateLit(name, color, 0.05f, 0.72f);
            if (!material.HasProperty("_EmissionColor"))
                return material;
            material.EnableKeyword("_EMISSION");
            material.SetColor("_EmissionColor", color * intensity);
            if (material.HasProperty("_EmissiveColor"))
                material.SetColor("_EmissiveColor", color * intensity);
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            return material;
        }

        private Material CreateTransparent(string name, Color color, float smoothness)
        {
            var material = CreateLit(name, color, 0.12f, smoothness);
            material.SetFloat("_SurfaceType", 1f);
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            material.SetInt("_ZWrite", 0);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = 3000;
            return material;
        }

        private Texture2D CreateTerrazzoTexture()
        {
            const int size = 512;
            const int tile = 128;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, true)
            {
                name = "B1 terrazzo tile albedo",
                wrapMode = TextureWrapMode.Repeat,
                filterMode = FilterMode.Trilinear,
                anisoLevel = 8
            };
            var random = new System.Random(7301);
            var pixels = new Color32[size * size];
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var grout = x % tile < 2 || y % tile < 2;
                    var noise = random.Next(-5, 6);
                    var fleck = random.NextDouble() < 0.026 ? random.Next(-34, 25) : 0;
                    var baseValue = grout ? 145 + noise : 177 + noise + fleck;
                    pixels[y * size + x] = new Color32(
                        (byte)Mathf.Clamp(baseValue - 3, 0, 255),
                        (byte)Mathf.Clamp(baseValue, 0, 255),
                        (byte)Mathf.Clamp(baseValue + 2, 0, 255),
                        255);
                }
            }
            texture.SetPixels32(pixels);
            texture.Apply(true, false);
            _resources.Add(texture);
            return texture;
        }

        private Texture2D CreatePerforatedTexture()
        {
            const int size = 128;
            const int spacing = 16;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, true)
            {
                name = "B1 perforated panel albedo",
                wrapMode = TextureWrapMode.Repeat,
                filterMode = FilterMode.Trilinear,
                anisoLevel = 4
            };
            var pixels = new Color32[size * size];
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var dx = x % spacing - spacing * 0.5f;
                    var dy = y % spacing - spacing * 0.5f;
                    var hole = dx * dx + dy * dy < 4.5f;
                    var value = hole ? 48 : 188;
                    pixels[y * size + x] = new Color32((byte)value, (byte)value, (byte)(value + 2), 255);
                }
            }
            texture.SetPixels32(pixels);
            texture.Apply(true, false);
            _resources.Add(texture);
            return texture;
        }
    }
}
