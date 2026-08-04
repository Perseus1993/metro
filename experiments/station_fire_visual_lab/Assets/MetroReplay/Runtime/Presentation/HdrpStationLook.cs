using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace MetroReplay.Presentation
{
    internal static class HdrpStationLook
    {
        public static void Build(Transform parent, Bounds bounds)
        {
            BuildGlobalVolume(parent);
            BuildInteriorLights(parent);
            if (Object.FindFirstObjectByType<ReflectionProbe>() == null)
                BuildReflectionProbe(parent, bounds.center, ExpandedProbeSize(bounds));
        }

        public static void ConfigureCamera(Camera camera)
        {
            camera.usePhysicalProperties = true;
            camera.allowDynamicResolution = false;
            camera.sensorSize = new Vector2(36f, 24f);
            camera.focalLength = 32f;
            camera.gateFit = Camera.GateFitMode.Vertical;
            var additional = camera.gameObject.GetComponent<HDAdditionalCameraData>()
                ?? camera.gameObject.AddComponent<HDAdditionalCameraData>();
            additional.allowDynamicResolution = false;
            additional.antialiasing = HDAdditionalCameraData.AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            additional.SMAAQuality = HDAdditionalCameraData.SMAAQualityLevel.High;
            additional.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
            additional.backgroundColorHDR = camera.backgroundColor;
            additional.clearDepth = true;
        }

        public static void KeepOnlyGeneratedDirectionalLight(Light retainedLight)
        {
            if (retainedLight == null)
                return;

            var lights = Object.FindObjectsByType<Light>(
                FindObjectsInactive.Include,
                FindObjectsSortMode.None);
            foreach (var light in lights)
            {
                if (light == null || light == retainedLight || light.type != LightType.Directional)
                    continue;

                light.shadows = LightShadows.None;
                light.enabled = false;
            }
        }

        public static void EnsureAdditionalLightData(Light light)
        {
            var additional = light.GetComponent<HDAdditionalLightData>()
                ?? light.gameObject.AddComponent<HDAdditionalLightData>();
            additional.useContactShadow.useOverride = true;
            additional.useContactShadow.@override = true;
        }

        public static ReflectionProbe BuildReflectionProbe(
            Transform parent, Vector3 center, Vector3 size)
        {
            var probeObject = new GameObject("HDRP Reflection Probe");
            probeObject.transform.SetParent(parent, false);
            probeObject.transform.position = center;
            var probe = probeObject.AddComponent<ReflectionProbe>();
            probe.mode = ReflectionProbeMode.Realtime;
            probe.refreshMode = ReflectionProbeRefreshMode.ViaScripting;
            probe.timeSlicingMode = ReflectionProbeTimeSlicingMode.IndividualFaces;
            probe.size = size;
            probe.resolution = 256;
            probe.intensity = 1.05f;
            if (probeObject.GetComponent<HDAdditionalReflectionData>() == null)
                probeObject.AddComponent<HDAdditionalReflectionData>();
            probe.RequestRenderNextUpdate();
            return probe;
        }

        private static void BuildGlobalVolume(Transform parent)
        {
            var volumeObject = new GameObject("HDRP Station Look Volume");
            volumeObject.transform.SetParent(parent, false);
            var volume = volumeObject.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 100f;
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            profile.name = "Metro Replay Runtime HDRP Look";
            volume.sharedProfile = profile;

            var ao = profile.Add<ScreenSpaceAmbientOcclusion>(true);
            ao.intensity.Override(1.05f);
            ao.radius.Override(0.75f);
            ao.directLightingStrength.Override(0.18f);

            var contactShadows = profile.Add<ContactShadows>(true);
            contactShadows.enable.Override(true);
            contactShadows.length.Override(0.35f);
            contactShadows.opacity.Override(0.82f);
            contactShadows.maxDistance.Override(55f);
            contactShadows.fadeDistance.Override(10f);

            var gi = profile.Add<GlobalIllumination>(true);
            gi.enable.Override(true);
            gi.fullResolutionSS.Override(false);

            var reflections = profile.Add<ScreenSpaceReflection>(true);
            reflections.enabled.Override(true);
            reflections.enabledTransparent.Override(true);

            var indirect = profile.Add<IndirectLightingController>(true);
            indirect.indirectDiffuseLightingMultiplier.Override(1.15f);
            indirect.reflectionLightingMultiplier.Override(0.96f);
            indirect.reflectionProbeIntensityMultiplier.Override(0.96f);

            var exposure = profile.Add<Exposure>(true);
            exposure.mode.Override(ExposureMode.Fixed);
            exposure.fixedExposure.Override(8.0f);

            var whiteBalance = profile.Add<WhiteBalance>(true);
            whiteBalance.temperature.Override(-4f);
            whiteBalance.tint.Override(1f);

            var color = profile.Add<ColorAdjustments>(true);
            color.contrast.Override(8f);
            color.saturation.Override(-4f);
            color.colorFilter.Override(new Color(0.98f, 0.99f, 1f));

            var tonemapping = profile.Add<Tonemapping>(true);
            tonemapping.mode.Override(TonemappingMode.ACES);

            var bloom = profile.Add<Bloom>(true);
            bloom.intensity.Override(0.06f);
            bloom.threshold.Override(1.30f);
            bloom.scatter.Override(0.50f);
        }

        private static void BuildInteriorLights(Transform parent)
        {
            var fixtureMaterial = BuildFixtureMaterial();
            var renderers = parent.GetComponentsInChildren<Renderer>(true);
            foreach (var levelRenderer in renderers)
            {
                if (!levelRenderer.gameObject.name.StartsWith("Level_"))
                    continue;

                var levelBounds = levelRenderer.bounds;
                if (levelBounds.size.x < 2f || levelBounds.size.z < 2f)
                    continue;

                var xCount = Mathf.Clamp(Mathf.CeilToInt(levelBounds.size.x / 12f), 2, 8);
                var zCount = Mathf.Clamp(Mathf.CeilToInt(levelBounds.size.z / 10f), 2, 6);
                for (var xIndex = 0; xIndex < xCount; xIndex++)
                {
                    var x = Mathf.Lerp(
                        levelBounds.min.x,
                        levelBounds.max.x,
                        (xIndex + 0.5f) / xCount);
                    for (var zIndex = 0; zIndex < zCount; zIndex++)
                    {
                        var z = Mathf.Lerp(
                            levelBounds.min.z,
                            levelBounds.max.z,
                            (zIndex + 0.5f) / zCount);
                        AddInteriorLight(
                            parent,
                            new Vector3(x, levelBounds.max.y + 3.35f, z),
                            fixtureMaterial);
                    }
                }
            }
        }

        private static void AddInteriorLight(
            Transform parent,
            Vector3 position,
            Material fixtureMaterial)
        {
            if (fixtureMaterial != null)
            {
                var fixture = B1HeroGeometryFactory.Box(
                    parent,
                    "StationLinearCeilingLight",
                    position + Vector3.up * 0.34f,
                    new Vector3(3.6f, 0.055f, 0.34f),
                    fixtureMaterial);
                var fixtureRenderer = fixture.GetComponent<Renderer>();
                fixtureRenderer.shadowCastingMode = ShadowCastingMode.Off;
                fixtureRenderer.receiveShadows = false;
            }

            var lightObject = new GameObject("StationCeilingFill");
            lightObject.transform.SetParent(parent, false);
            lightObject.transform.position = position;

            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = new Color(1.0f, 0.95f, 0.86f);
            light.intensity = 2600f;
            light.range = 9.5f;
            light.bounceIntensity = 1.15f;
            light.shadows = LightShadows.None;
            light.renderMode = LightRenderMode.ForcePixel;
            EnsureAdditionalLightData(light);
        }

        private static Material BuildFixtureMaterial()
        {
            var shader = Shader.Find("HDRP/Lit");
            if (shader == null)
                return null;

            var color = new Color(1.0f, 0.96f, 0.88f);
            var material = new Material(shader) { name = "Station linear ceiling light" };
            material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Metallic"))
                material.SetFloat("_Metallic", 0.02f);
            if (material.HasProperty("_Smoothness"))
                material.SetFloat("_Smoothness", 0.72f);
            if (material.HasProperty("_EmissionColor"))
            {
                material.EnableKeyword("_EMISSION");
                material.SetColor("_EmissionColor", color * 7.5f);
            }
            if (material.HasProperty("_EmissiveColor"))
                material.SetColor("_EmissiveColor", color * 7.5f);
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            return material;
        }

        private static Vector3 ExpandedProbeSize(Bounds bounds)
        {
            return new Vector3(
                Mathf.Clamp(bounds.size.x, 12f, 60f),
                Mathf.Clamp(bounds.size.y, 5f, 18f),
                Mathf.Clamp(bounds.size.z, 12f, 60f));
        }
    }
}
