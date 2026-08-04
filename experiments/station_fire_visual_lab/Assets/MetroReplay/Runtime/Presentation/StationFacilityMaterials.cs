using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class StationFacilityMaterials
    {
        private readonly Dictionary<string, Material> _cache = new Dictionary<string, Material>();

        public Material Steel => Get("steel", new Color(0.48f, 0.53f, 0.58f), 0.82f, 0.72f);
        public Material DarkMetal => Get("dark-metal", new Color(0.045f, 0.055f, 0.068f), 0.72f, 0.62f);
        public Material Rubber => Get("rubber", new Color(0.025f, 0.03f, 0.036f), 0.05f, 0.32f);
        public Material Step => Get("step", new Color(0.34f, 0.37f, 0.39f), 0.64f, 0.58f);
        public Material GateBlue => Get("gate-blue", new Color(0.04f, 0.24f, 0.54f), 0.52f, 0.66f);
        public Material DoorFrame => Get("door-frame", new Color(0.34f, 0.38f, 0.42f), 0.88f, 0.72f);
        public Material DoorPanel => Get("door-panel", new Color(0.66f, 0.69f, 0.71f), 0.76f, 0.62f);
        public Material Glass => GetTransparent("glass", new Color(0.18f, 0.46f, 0.56f, 0.20f));
        public Material Green => GetEmissive("green", new Color(0.03f, 0.82f, 0.38f), 3.2f);
        public Material Red => GetEmissive("red", new Color(0.92f, 0.06f, 0.04f), 2.4f);
        public Material Amber => GetEmissive("amber", new Color(1f, 0.48f, 0.03f), 2.0f);

        private Material Get(string key, Color color, float metallic, float smoothness)
        {
            if (_cache.TryGetValue(key, out var material))
                return material;
            material = ReplayMaterialFactory.Create("Facility_" + key, color);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Smoothness", smoothness);
            _cache[key] = material;
            return material;
        }

        private Material GetTransparent(string key, Color color)
        {
            var material = Get(key, color, 0.12f, 0.86f);
            material.SetFloat("_SurfaceType", 1f);
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            material.SetInt("_ZWrite", 0);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = 3000;
            return material;
        }

        private Material GetEmissive(string key, Color color, float intensity)
        {
            var material = Get(key, color, 0.12f, 0.72f);
            material.SetColor("_EmissiveColor", color * intensity);
            material.EnableKeyword("_EMISSIVE_COLOR_MAP");
            return material;
        }
    }
}
