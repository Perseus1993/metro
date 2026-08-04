using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Presentation
{
    internal static class B1HeroLighting
    {
        public static void Build(
            Transform parent,
            Vector3 shellCenter,
            IReadOnlyList<Vector3> bayCenters,
            float floorY,
            float width,
            float depth)
        {
            QualitySettings.pixelLightCount = 12;
            QualitySettings.antiAliasing = 4;
            QualitySettings.shadows = ShadowQuality.All;
            QualitySettings.shadowResolution = ShadowResolution.High;
            QualitySettings.shadowDistance = 42f;

            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.54f, 0.56f, 0.59f);
            RenderSettings.ambientEquatorColor = new Color(0.40f, 0.42f, 0.45f);
            RenderSettings.ambientGroundColor = new Color(0.22f, 0.23f, 0.25f);
            RenderSettings.ambientIntensity = 1.0f;
            RenderSettings.reflectionIntensity = 0.96f;

            var key = new GameObject("HeroSoftKeyLight");
            key.transform.SetParent(parent, false);
            key.transform.rotation = Quaternion.Euler(58f, -28f, 0f);
            var directional = key.AddComponent<Light>();
            directional.type = LightType.Directional;
            directional.color = new Color(0.92f, 0.94f, 1f);
            directional.intensity = 500f;
            directional.shadows = LightShadows.Soft;
            directional.shadowStrength = 0.55f;
            HdrpStationLook.EnsureAdditionalLightData(directional);
            HdrpStationLook.KeepOnlyGeneratedDirectionalLight(directional);

            var xLimit = width * 0.5f - 3.5f;
            var zLimit = depth * 0.5f - 3.5f;
            for (var xOffset = -xLimit; xOffset <= xLimit; xOffset += 8f)
            {
                for (var zOffset = -zLimit; zOffset <= zLimit; zOffset += 4.5f)
                    AddCeilingLight(parent, shellCenter + new Vector3(xOffset, 4.10f, zOffset), floorY);
            }

            foreach (var bayCenter in bayCenters)
            {
                AddGateSpot(parent, bayCenter + new Vector3(-5.2f, 3.7f, 0.6f), floorY);
                AddGateSpot(parent, bayCenter + new Vector3(5.2f, 3.7f, 0.6f), floorY);
            }

            HdrpStationLook.BuildReflectionProbe(
                parent,
                shellCenter + Vector3.up * 1.8f,
                new Vector3(width - 2f, 5f, depth - 2f));
        }

        private static void AddCeilingLight(Transform parent, Vector3 position, float floorY)
        {
            var lightObject = new GameObject("HeroCeilingLight");
            lightObject.transform.SetParent(parent, false);
            lightObject.transform.position = new Vector3(position.x, floorY + 4.15f, position.z);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = new Color(0.94f, 0.96f, 1f);
            light.intensity = 1800f;
            light.range = 8.2f;
            light.shadows = LightShadows.None;
            light.renderMode = LightRenderMode.ForcePixel;
            HdrpStationLook.EnsureAdditionalLightData(light);
        }

        private static void AddGateSpot(Transform parent, Vector3 position, float floorY)
        {
            var lightObject = new GameObject("HeroGateSpot");
            lightObject.transform.SetParent(parent, false);
            lightObject.transform.position = new Vector3(position.x, floorY + 3.7f, position.z);
            lightObject.transform.rotation = Quaternion.Euler(72f, 0f, 0f);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Spot;
            light.color = new Color(0.91f, 0.94f, 1f);
            light.intensity = 1600f;
            light.range = 9f;
            light.spotAngle = 54f;
            light.shadows = LightShadows.Soft;
            light.shadowStrength = 0.38f;
            HdrpStationLook.EnsureAdditionalLightData(light);
        }
    }
}
