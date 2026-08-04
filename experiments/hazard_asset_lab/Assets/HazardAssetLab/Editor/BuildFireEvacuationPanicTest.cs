using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HazardAssetLab.EditorTools
{
    public static class BuildFireEvacuationPanicTest
    {
        private const string RootFolder = "Assets/HazardAssetLab";
        private const string SceneFolder = RootFolder + "/Scenes";
        private const string MaterialFolder = RootFolder + "/Materials/FireEvacuationTest";
        private const string ScenePath = SceneFolder + "/MetroStationFireEvacuationTest.unity";
        private const string VolumeProfilePath = MaterialFolder + "/MetroStationFirePostProcess.asset";
        private const string ResidentRoot = RootFolder + "/ThirdParty/MetroReplayResidents";
        private const string StationAssetRoot = RootFolder + "/ThirdParty/MetroReplayStation";
        private const string FirePrefabPath = "Assets/Vefects/Free Fire HDRP/Particles/VFX_Fire_01_Medium_Smoke.prefab";

        private static readonly string[] ResidentPrefabPaths =
        {
            ResidentRoot + "/Generated/Prefabs/Male_Adult_03.prefab",
            ResidentRoot + "/Generated/Prefabs/Female_Adult_05.prefab"
        };

        private static readonly string[] RunAnimationPaths =
        {
            ResidentRoot + "/RocketboxAnimations/m_run_neutral.max.fbx",
            ResidentRoot + "/RocketboxAnimations/f_run_neutral.max.fbx"
        };

        private static readonly string[] TrainCarPrefabPaths =
        {
            StationAssetRoot + "/Trains/MetroCar_Head_Kenney.prefab",
            StationAssetRoot + "/Trains/MetroCar_Middle_Kenney.prefab",
            StationAssetRoot + "/Trains/MetroCar_Tail_Kenney.prefab"
        };

        private static readonly Vector3[] RunnerStarts =
        {
            new(-4.6f, 0f, -1.7f),
            new(-2.5f, 0f, -0.5f),
            new(2.4f, 0f, -0.6f),
            new(4.7f, 0f, -1.9f),
            new(-5.1f, 0f, 2.5f),
            new(-2.7f, 0f, 3.5f),
            new(2.8f, 0f, 3.6f),
            new(5.2f, 0f, 2.4f)
        };

        [MenuItem("Hazard Asset Lab/Build Metro Station Fire + Panic Test")]
        public static void Build()
        {
            try
            {
                EnsureFolder(SceneFolder);
                EnsureFolder(MaterialFolder);

                GameObject[] residentPrefabs = ResidentPrefabPaths
                    .Select(AssetDatabase.LoadAssetAtPath<GameObject>)
                    .ToArray();
                if (residentPrefabs.Any(prefab => prefab == null))
                {
                    throw new FileNotFoundException("One or more Rocketbox resident prefabs were not found.");
                }

                AnimationClip[] runClips = RunAnimationPaths
                    .Select(LoadRunClip)
                    .ToArray();
                GameObject firePrefab = AssetDatabase.LoadAssetAtPath<GameObject>(FirePrefabPath);
                if (firePrefab == null)
                {
                    throw new FileNotFoundException("Fire prefab was not found.", FirePrefabPath);
                }

                GameObject[] trainCarPrefabs = TrainCarPrefabPaths
                    .Select(AssetDatabase.LoadAssetAtPath<GameObject>)
                    .ToArray();
                if (trainCarPrefabs.Any(prefab => prefab == null))
                {
                    throw new FileNotFoundException("One or more copied metro train prefabs were not found.");
                }

                var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
                BuildEnvironment();
                BuildTrain(trainCarPrefabs);
                BuildFire(firePrefab);
                BuildRunners(residentPrefabs, runClips);
                BuildLightingAndCamera();
                BuildPostProcessing();

                var controller = new GameObject("FireEvacuationDemo");
                controller.AddComponent<FireEvacuationDemoHud>();

                EditorSceneManager.SaveScene(scene, ScenePath);
                AssetDatabase.SaveAssets();
                Selection.activeGameObject = controller;
                SceneView.lastActiveSceneView?.FrameSelected();

                Debug.Log($"[HazardAssetLab] Metro station fire + Rocketbox panic run test built at {ScenePath}. Runners={RunnerStarts.Length}, clip=Jog_Fwd_Loop.");
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
            }
        }

        private static AnimationClip LoadRunClip(string assetPath)
        {
            AnimationClip clip = AssetDatabase.LoadAllAssetsAtPath(assetPath)
                .OfType<AnimationClip>()
                .FirstOrDefault(candidate =>
                    string.Equals(candidate.name, "Jog_Fwd_Loop", StringComparison.Ordinal));

            if (clip == null)
            {
                throw new InvalidOperationException($"Jog_Fwd_Loop was not found in {assetPath}.");
            }

            return clip;
        }

        private static void BuildEnvironment()
        {
            Material floorMaterial = CreateMaterial("MetroPlatform_Floor", new Color(0.27f, 0.29f, 0.31f), 0.04f, 0.34f);
            Material wallMaterial = CreateMaterial("MetroPlatform_Wall", new Color(0.63f, 0.68f, 0.73f), 0.02f, 0.22f);
            Material blueMaterial = CreateMaterial("MetroPlatform_LineBlue", new Color(0.035f, 0.19f, 0.43f), 0.05f, 0.38f);
            Material darkMaterial = CreateMaterial("MetroPlatform_Dark", new Color(0.018f, 0.025f, 0.036f), 0.02f, 0.16f);
            Material metalMaterial = CreateMaterial("MetroPlatform_Metal", new Color(0.28f, 0.32f, 0.36f), 0.72f, 0.52f);
            Material glassMaterial = CreateMaterial("MetroPlatform_GlassTint", new Color(0.07f, 0.18f, 0.24f), 0.08f, 0.72f);
            Material tactileMaterial = CreateMaterial("MetroPlatform_Tactile", new Color(0.78f, 0.55f, 0.045f), 0f, 0.28f);
            Material lightMaterial = CreateMaterial("MetroPlatform_LinearLight", new Color(0.84f, 0.89f, 0.92f), 0f, 0.35f, new Color(3.5f, 3.7f, 3.9f));
            Material exitMaterial = CreateMaterial("MetroPlatform_Exit", new Color(0.015f, 0.32f, 0.09f), 0f, 0.24f, new Color(0.02f, 1.1f, 0.18f));
            Material dangerMaterial = CreateMaterial("MetroPlatform_Danger", new Color(0.42f, 0.035f, 0.012f), 0f, 0.18f, new Color(0.9f, 0.055f, 0.008f));

            var environment = new GameObject("MetroStationPlatform_VisualOnly");

            CreateBox("PlatformFloor", new Vector3(0f, -0.2f, 0.25f), new Vector3(36f, 0.4f, 11.1f), floorMaterial, environment.transform);
            CreateBox("TrackBed", new Vector3(0f, -0.56f, 8.25f), new Vector3(38f, 0.72f, 5.1f), darkMaterial, environment.transform);
            CreateBox("TunnelBackWall", new Vector3(0f, 2.35f, 11f), new Vector3(38f, 5.3f, 0.35f), wallMaterial, environment.transform);
            CreateBox("TunnelBlueBand", new Vector3(0f, 3.1f, 10.78f), new Vector3(38f, 0.72f, 0.08f), blueMaterial, environment.transform);

            CreateBox("Rail_Near", new Vector3(0f, -0.12f, 7.15f), new Vector3(38f, 0.13f, 0.12f), metalMaterial, environment.transform);
            CreateBox("Rail_Far", new Vector3(0f, -0.12f, 9.15f), new Vector3(38f, 0.13f, 0.12f), metalMaterial, environment.transform);
            for (int sleeper = -17; sleeper <= 17; sleeper += 1)
            {
                CreateBox($"TrackSleeper_{sleeper + 18:00}", new Vector3(sleeper, -0.28f, 8.15f), new Vector3(0.16f, 0.12f, 3.2f), metalMaterial, environment.transform);
            }

            CreateBox("PlatformTactileStrip", new Vector3(0f, 0.028f, 4.72f), new Vector3(36f, 0.055f, 0.38f), tactileMaterial, environment.transform);
            CreateBox("PlatformWhiteSafetyLine", new Vector3(0f, 0.032f, 4.25f), new Vector3(36f, 0.06f, 0.11f), lightMaterial, environment.transform);

            for (int module = -4; module <= 4; module++)
            {
                float x = module * 4f;
                CreateBox($"PlatformDoorPost_{module + 5:00}", new Vector3(x, 1.25f, 5.32f), new Vector3(0.16f, 2.5f, 0.18f), metalMaterial, environment.transform);
                if (module < 4)
                {
                    CreateBox($"PlatformDoorGlass_{module + 5:00}", new Vector3(x + 2f, 1.42f, 5.35f), new Vector3(3.72f, 1.72f, 0.07f), glassMaterial, environment.transform);
                    CreateBox($"PlatformDoorHeader_{module + 5:00}", new Vector3(x + 2f, 2.52f, 5.32f), new Vector3(3.9f, 0.25f, 0.2f), blueMaterial, environment.transform);
                }
            }

            for (int columnIndex = -2; columnIndex <= 2; columnIndex++)
            {
                if (columnIndex == 0)
                {
                    continue;
                }

                float x = columnIndex * 6.4f;
                CreateBox($"PlatformColumn_{columnIndex + 3:00}", new Vector3(x, 2.35f, 0.9f), new Vector3(0.72f, 4.7f, 0.72f), wallMaterial, environment.transform);
                CreateBox($"PlatformColumnBlueBand_{columnIndex + 3:00}", new Vector3(x, 2.65f, 0.9f), new Vector3(0.77f, 1.15f, 0.77f), blueMaterial, environment.transform);
            }

            CreateBox("CeilingBeam_Back", new Vector3(0f, 4.85f, 7.8f), new Vector3(38f, 0.38f, 0.72f), darkMaterial, environment.transform);
            CreateBox("CeilingBeam_Front", new Vector3(0f, 4.85f, -2.8f), new Vector3(38f, 0.38f, 0.72f), darkMaterial, environment.transform);
            for (int lightIndex = -3; lightIndex <= 3; lightIndex++)
            {
                float x = lightIndex * 4.6f;
                CreateBox($"LinearLight_{lightIndex + 4:00}", new Vector3(x, 4.64f, 2.0f), new Vector3(3.2f, 0.08f, 0.18f), lightMaterial, environment.transform);
            }

            CreateExitPortal("Exit_Left", -15.5f, exitMaterial, darkMaterial, environment.transform);
            CreateExitPortal("Exit_Right", 15.5f, exitMaterial, darkMaterial, environment.transform);

            CreateBox("StationNameSign", new Vector3(0f, 3.9f, -1.5f), new Vector3(8.4f, 0.92f, 0.2f), darkMaterial, environment.transform);
            CreateBox("StationNameBlueLine", new Vector3(0f, 3.58f, -1.61f), new Vector3(8f, 0.12f, 0.06f), blueMaterial, environment.transform);
            CreateTextLabel("StationNameLabel", "DEMO STATION  |  PLATFORM 1", new Vector3(0f, 3.92f, -1.62f), 0.085f, Color.white, environment.transform);

            CreateBench("Bench_Left", new Vector3(-8.5f, 0f, -2.2f), metalMaterial, blueMaterial, environment.transform);
            CreateBench("Bench_Right", new Vector3(8.5f, 0f, -2.2f), metalMaterial, blueMaterial, environment.transform);

            GameObject dangerRing = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            dangerRing.name = "FireDangerMarker";
            dangerRing.transform.SetParent(environment.transform, false);
            dangerRing.transform.position = new Vector3(0f, -0.04f, 1f);
            dangerRing.transform.localScale = new Vector3(2.2f, 0.025f, 2.2f);
            dangerRing.GetComponent<MeshRenderer>().sharedMaterial = dangerMaterial;
            UnityEngine.Object.DestroyImmediate(dangerRing.GetComponent<Collider>());

            GameObject safeCenter = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            safeCenter.name = "FireBaseDarkener";
            safeCenter.transform.SetParent(environment.transform, false);
            safeCenter.transform.position = new Vector3(0f, -0.015f, 1f);
            safeCenter.transform.localScale = new Vector3(1.55f, 0.03f, 1.55f);
            safeCenter.GetComponent<MeshRenderer>().sharedMaterial = floorMaterial;
            UnityEngine.Object.DestroyImmediate(safeCenter.GetComponent<Collider>());
        }

        private static void CreateExitPortal(string name, float x, Material exitMaterial, Material frameMaterial, Transform parent)
        {
            float sign = Mathf.Sign(x);
            CreateBox(name + "_Back", new Vector3(x, 1.65f, -0.9f), new Vector3(2.8f, 3.3f, 0.35f), frameMaterial, parent);
            CreateBox(name + "_Opening", new Vector3(x - sign * 0.12f, 1.4f, -1.12f), new Vector3(2.05f, 2.45f, 0.08f), exitMaterial, parent);
            CreateBox(name + "_Sign", new Vector3(x, 3.48f, -1.05f), new Vector3(2.5f, 0.58f, 0.22f), exitMaterial, parent);
            CreateTextLabel(name + "_Label", sign < 0f ? "EXIT  <<" : ">>  EXIT", new Vector3(x, 3.5f, -1.18f), 0.095f, Color.white, parent);

            for (int step = 0; step < 5; step++)
            {
                CreateBox(
                    name + $"_Step_{step:00}",
                    new Vector3(x - sign * (0.25f + step * 0.34f), 0.08f + step * 0.09f, -0.35f + step * 0.24f),
                    new Vector3(2.1f, 0.16f, 0.48f),
                    frameMaterial,
                    parent);
            }
        }

        private static void CreateBench(string name, Vector3 position, Material metal, Material seat, Transform parent)
        {
            CreateBox(name + "_Seat", position + new Vector3(0f, 0.55f, 0f), new Vector3(3.1f, 0.18f, 0.68f), seat, parent);
            CreateBox(name + "_Back", position + new Vector3(0f, 1.1f, 0.28f), new Vector3(3.1f, 0.82f, 0.14f), seat, parent);
            CreateBox(name + "_LegA", position + new Vector3(-1.1f, 0.27f, 0f), new Vector3(0.18f, 0.54f, 0.55f), metal, parent);
            CreateBox(name + "_LegB", position + new Vector3(1.1f, 0.27f, 0f), new Vector3(0.18f, 0.54f, 0.55f), metal, parent);
        }

        private static void CreateTextLabel(string name, string text, Vector3 position, float characterSize, Color color, Transform parent)
        {
            var label = new GameObject(name);
            label.transform.SetParent(parent, false);
            label.transform.SetPositionAndRotation(position, Quaternion.identity);
            TextMesh textMesh = label.AddComponent<TextMesh>();
            textMesh.text = text;
            textMesh.anchor = TextAnchor.MiddleCenter;
            textMesh.alignment = TextAlignment.Center;
            textMesh.fontSize = 72;
            textMesh.characterSize = characterSize;
            textMesh.color = color;
        }

        private static void BuildTrain(GameObject[] trainCarPrefabs)
        {
            var trainRoot = new GameObject("StaticMetroTrain_VisualOnly");
            float[] carPositions = { -11.6f, 0f, 11.6f };

            for (int index = 0; index < trainCarPrefabs.Length; index++)
            {
                GameObject car = (GameObject)PrefabUtility.InstantiatePrefab(trainCarPrefabs[index]);
                car.name = $"TrainCar_{index + 1:00}_{trainCarPrefabs[index].name}";
                car.transform.SetParent(trainRoot.transform, true);
                car.transform.SetPositionAndRotation(
                    new Vector3(carPositions[index], -0.3f, 8.15f),
                    Quaternion.Euler(0f, 90f, 0f));
            }
        }

        private static void BuildFire(GameObject firePrefab)
        {
            GameObject fire = (GameObject)PrefabUtility.InstantiatePrefab(firePrefab);
            fire.name = "Fire_Source_MediumSmoke";
            fire.transform.position = new Vector3(0f, 0f, 1f);
            fire.transform.localScale = Vector3.one * 1.65f;

            // The vendor prefab uses a particle Lights module. In HDRP that can spawn
            // dozens of physical lights and overexpose a small test scene at runtime.
            // Keep the original flame/smoke particles and replace only that lighting
            // with one controlled point light on this scene instance.
            foreach (ParticleSystem particleSystem in fire.GetComponentsInChildren<ParticleSystem>(true))
            {
                ParticleSystem.LightsModule lights = particleSystem.lights;
                if (lights.enabled)
                {
                    lights.enabled = false;
                }
            }

            Light fireLight = new GameObject("Fire_PointLight").AddComponent<Light>();
            fireLight.type = LightType.Point;
            fireLight.color = new Color(1f, 0.28f, 0.055f);
            fireLight.intensity = 850f;
            fireLight.range = 6f;
            fireLight.transform.position = new Vector3(0f, 1.35f, 1f);
            if (fireLight.GetComponent<HDAdditionalLightData>() == null)
            {
                fireLight.gameObject.AddComponent<HDAdditionalLightData>();
            }
        }

        private static void BuildRunners(GameObject[] residentPrefabs, AnimationClip[] runClips)
        {
            var runnersRoot = new GameObject("PanicPassengers");
            var targetsRoot = new GameObject("ExitTargets");

            for (int index = 0; index < RunnerStarts.Length; index++)
            {
                Vector3 start = RunnerStarts[index];
                float side = start.x < 0f ? -1f : 1f;
                Vector3 targetPosition = new Vector3(side * 16.4f, 0f, -0.75f + (index % 2) * 0.45f);

                GameObject target = new GameObject($"ExitTarget_{index + 1:00}");
                target.transform.SetParent(targetsRoot.transform, false);
                target.transform.position = targetPosition;

                // Movement/facing lives on a clean wrapper. The resident prefab remains
                // at identity underneath it, so its humanoid animation cannot reverse
                // the world-space evacuation direction.
                var runner = new GameObject($"Passenger_{index + 1:00}");
                runner.transform.SetParent(runnersRoot.transform, false);
                runner.transform.position = start;

                int residentIndex = index % residentPrefabs.Length;
                GameObject avatar = (GameObject)PrefabUtility.InstantiatePrefab(residentPrefabs[residentIndex]);
                avatar.name = residentPrefabs[residentIndex].name + "_Visual";
                avatar.transform.SetParent(runner.transform, false);
                avatar.transform.SetLocalPositionAndRotation(Vector3.zero, Quaternion.identity);

                Animator animator = avatar.GetComponentInChildren<Animator>(true);
                if (animator == null)
                {
                    throw new InvalidOperationException($"Rocketbox resident {avatar.name} has no Animator.");
                }

                animator.applyRootMotion = false;
                animator.runtimeAnimatorController = null;

                PanicRunner panicRunner = runner.AddComponent<PanicRunner>();
                panicRunner.Configure(
                    runClips[residentIndex],
                    target.transform,
                    0.75f + index * 0.1f,
                    3.6f + (index % 3) * 0.28f,
                    1.1f + (index % 2) * 0.08f,
                    1.25f + (index % 3) * 0.12f);
            }
        }

        private static void BuildLightingAndCamera()
        {
            Light key = new GameObject("Station_KeyLight").AddComponent<Light>();
            key.type = LightType.Directional;
            key.color = new Color(0.78f, 0.86f, 1f);
            key.intensity = 36000f;
            key.transform.rotation = Quaternion.Euler(52f, -28f, 0f);
            if (key.GetComponent<HDAdditionalLightData>() == null)
            {
                key.gameObject.AddComponent<HDAdditionalLightData>();
            }

            for (int lightIndex = -2; lightIndex <= 2; lightIndex++)
            {
                Light stationLight = new GameObject($"Station_FillLight_{lightIndex + 3:00}").AddComponent<Light>();
                stationLight.type = LightType.Point;
                stationLight.color = new Color(0.82f, 0.9f, 1f);
                stationLight.intensity = 950f;
                stationLight.range = 10f;
                stationLight.transform.position = new Vector3(lightIndex * 6.2f, 4.25f, 1.5f);
                if (stationLight.GetComponent<HDAdditionalLightData>() == null)
                {
                    stationLight.gameObject.AddComponent<HDAdditionalLightData>();
                }
            }

            Camera camera = new GameObject("PanicTestCamera").AddComponent<Camera>();
            camera.tag = "MainCamera";
            camera.gameObject.AddComponent<AudioListener>();
            HDAdditionalCameraData cameraData = camera.GetComponent<HDAdditionalCameraData>();
            if (cameraData == null)
            {
                cameraData = camera.gameObject.AddComponent<HDAdditionalCameraData>();
            }

            cameraData.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
            cameraData.backgroundColorHDR = new Color(0.012f, 0.016f, 0.024f, 1f);
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.012f, 0.016f, 0.024f, 1f);
            camera.fieldOfView = 58f;
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 90f;
            camera.transform.position = new Vector3(0f, 7.9f, -14.8f);
            camera.transform.LookAt(new Vector3(0f, 1.2f, 2.65f));
        }

        private static void BuildPostProcessing()
        {
            VolumeProfile profile = AssetDatabase.LoadAssetAtPath<VolumeProfile>(VolumeProfilePath);
            if (profile == null)
            {
                profile = ScriptableObject.CreateInstance<VolumeProfile>();
                profile.name = "FireEvacuationPostProcess";
                AssetDatabase.CreateAsset(profile, VolumeProfilePath);
            }

            if (!profile.TryGet(out Exposure exposure))
            {
                exposure = profile.Add<Exposure>(true);
            }

            exposure.mode.Override(ExposureMode.Fixed);
            exposure.fixedExposure.Override(10.4f);

            if (!profile.TryGet(out Tonemapping tonemapping))
            {
                tonemapping = profile.Add<Tonemapping>(true);
            }

            tonemapping.mode.Override(TonemappingMode.ACES);
            EditorUtility.SetDirty(profile);

            Volume volume = new GameObject("FireEvacuation_GlobalVolume").AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 100f;
            volume.sharedProfile = profile;
        }

        private static GameObject CreateBox(string name, Vector3 position, Vector3 scale, Material material, Transform parent)
        {
            GameObject box = GameObject.CreatePrimitive(PrimitiveType.Cube);
            box.name = name;
            box.transform.SetParent(parent, false);
            box.transform.position = position;
            box.transform.localScale = scale;
            box.GetComponent<MeshRenderer>().sharedMaterial = material;
            UnityEngine.Object.DestroyImmediate(box.GetComponent<Collider>());
            return box;
        }

        private static Material CreateMaterial(
            string name,
            Color baseColor,
            float metallic,
            float smoothness,
            Color? emission = null)
        {
            string path = $"{MaterialFolder}/{name}.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            Shader shader = Shader.Find("HDRP/Lit");
            if (shader == null)
            {
                throw new InvalidOperationException("HDRP/Lit shader is unavailable.");
            }

            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
            }

            if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", baseColor);
            if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", metallic);
            if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", smoothness);
            if (emission.HasValue && material.HasProperty("_EmissiveColor"))
            {
                material.SetColor("_EmissiveColor", emission.Value);
            }

            EditorUtility.SetDirty(material);
            return material;
        }

        private static void EnsureFolder(string folder)
        {
            string[] segments = folder.Split('/');
            string current = segments[0];
            for (int index = 1; index < segments.Length; index++)
            {
                string next = current + "/" + segments[index];
                if (!AssetDatabase.IsValidFolder(next))
                {
                    AssetDatabase.CreateFolder(current, segments[index]);
                }

                current = next;
            }
        }
    }
}
