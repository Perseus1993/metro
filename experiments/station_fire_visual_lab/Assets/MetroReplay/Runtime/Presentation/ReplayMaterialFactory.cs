using System;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class ReplayMaterialFactory
    {
        public static Material Create(string name, Color color)
        {
            var shader = Shader.Find("HDRP/Lit");
            if (shader == null)
                throw new InvalidOperationException("HDRP/Lit shader is unavailable. Configure HDRP before building the replay.");
            var material = new Material(shader) { name = name };
            material.SetColor("_BaseColor", color);
            material.SetFloat("_Metallic", 0.05f);
            material.SetFloat("_Smoothness", 0.48f);
            return material;
        }
    }
}
