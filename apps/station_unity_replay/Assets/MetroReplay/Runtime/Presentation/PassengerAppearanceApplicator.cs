using System;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal static class PassengerAppearanceApplicator
    {
        public static void Apply(
            Renderer[] renderers,
            int passengerId,
            MaterialPropertyBlock propertyBlock)
        {
            if (renderers == null)
                return;
            foreach (var renderer in renderers)
                ApplyRenderer(renderer, passengerId, propertyBlock);
        }

        private static void ApplyRenderer(
            Renderer renderer,
            int passengerId,
            MaterialPropertyBlock propertyBlock)
        {
            var materials = renderer.sharedMaterials;
            for (var index = 0; index < materials.Length; index++)
            {
                var name = materials[index] != null ? materials[index].name : string.Empty;
                var tint = SelectTint(name, passengerId);
                propertyBlock.Clear();
                propertyBlock.SetColor("_BaseColor", tint);
                propertyBlock.SetColor("_Color", tint);
                renderer.SetPropertyBlock(propertyBlock, index);
            }
        }

        private static Color SelectTint(string materialName, int passengerId)
        {
            if (materialName.IndexOf("head", StringComparison.OrdinalIgnoreCase) >= 0)
                return PassengerAppearancePalette.GetSkinTint(passengerId);
            if (materialName.IndexOf("opacity", StringComparison.OrdinalIgnoreCase) >= 0)
                return PassengerAppearancePalette.GetHairTint(passengerId);
            return PassengerAppearancePalette.GetClothingTint(passengerId);
        }
    }
}
