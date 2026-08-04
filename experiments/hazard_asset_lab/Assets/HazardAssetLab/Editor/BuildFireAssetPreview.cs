using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.VFX;

namespace HazardAssetLab.EditorTools
{
    public static class BuildFireAssetPreview
    {
        private const string RootFolder = "Assets/HazardAssetLab";
        private const string RenderingFolder = RootFolder + "/Rendering";
        private const string MaterialFolder = RootFolder + "/Materials/FirePreview";
        private const string SceneFolder = RootFolder + "/Scenes";
        private const string PreviewFolder = RootFolder + "/Previews";
        private const string ReportFolder = RootFolder + "/Reports";
        private const string PipelinePath = RenderingFolder + "/HazardLab_HDRP.asset";
        private const string ScenePath = SceneFolder + "/FireAssetPreview.unity";
        private const string PreviewPath = PreviewFolder + "/FireAssetPreview.png";
        private const string ReportPath = ReportFolder + "/FireAsset_Validation.md";
        private const string FlameRoot = "Assets/Solodream/VFX_FlamePack";
        private const string PreviewPrefabPath = FlameRoot + "/Prefabs/Flame_03.prefab";

        [MenuItem("Hazard Asset Lab/Prepare Fire Asset Preview Scene (Safe)")]
        public static void Build()
        {
            try
            {
                EnsureFolders();
                HDRenderPipelineAsset pipeline = EnsureHdrpPipeline();
                ValidationResult validation = ValidatePackage();
                CreatePreviewScene();
                WriteReport(
                    validation,
                    pipeline,
                    "Structural validation complete. Automated VFX playback and off-screen rendering are disabled for editor stability.");
                AssetDatabase.Refresh();
                Debug.Log($"[HazardAssetLab] Safe fire preview scene prepared. Prefabs={validation.PrefabCount}, VFX graphs={validation.VfxGraphCount}, missing references={validation.MissingReferenceCount}. No VFX simulation or preview rendering was started.");
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                if (Application.isBatchMode)
                {
                    EditorApplication.Exit(1);
                }
            }
        }

        private static HDRenderPipelineAsset EnsureHdrpPipeline()
        {
            PlayerSettings.colorSpace = ColorSpace.Linear;

            HDRenderPipelineAsset pipeline = AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>(PipelinePath);
            if (pipeline == null)
            {
                pipeline = ScriptableObject.CreateInstance<HDRenderPipelineAsset>();
                pipeline.name = "HazardLab_HDRP";
                AssetDatabase.CreateAsset(pipeline, PipelinePath);
            }

            GraphicsSettings.defaultRenderPipeline = pipeline;
            QualitySettings.renderPipeline = pipeline;
            EditorUtility.SetDirty(pipeline);
            AssetDatabase.SaveAssets();
            return pipeline;
        }

        private static ValidationResult ValidatePackage()
        {
            string[] prefabGuids = AssetDatabase.FindAssets("t:Prefab", new[] { FlameRoot });
            string[] vfxGuids = AssetDatabase.FindAssets("t:VisualEffectAsset", new[] { FlameRoot });
            var result = new ValidationResult
            {
                PrefabCount = prefabGuids.Length,
                VfxGraphCount = vfxGuids.Length
            };

            foreach (string guid in prefabGuids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null)
                {
                    result.Errors.Add($"Could not load prefab: {path}");
                    continue;
                }

                VisualEffect[] effects = prefab.GetComponentsInChildren<VisualEffect>(true);
                if (effects.Length == 0)
                {
                    result.Errors.Add($"Prefab has no VisualEffect component: {path}");
                }

                foreach (VisualEffect effect in effects)
                {
                    result.VisualEffectComponentCount++;
                    if (effect.visualEffectAsset == null)
                    {
                        result.Errors.Add($"VisualEffect has no graph assigned: {path}/{effect.name}");
                    }
                }

                result.MissingReferenceCount += CountMissingObjectReferences(prefab);
            }

            if (result.PrefabCount == 0)
            {
                result.Errors.Add("No fire prefabs were found.");
            }

            if (result.VfxGraphCount == 0)
            {
                result.Errors.Add("No Visual Effect Graph assets were found.");
            }

            return result;
        }

        private static int CountMissingObjectReferences(GameObject prefab)
        {
            int missing = 0;
            Component[] components = prefab.GetComponentsInChildren<Component>(true);
            foreach (Component component in components)
            {
                if (component == null)
                {
                    missing++;
                    continue;
                }

                var serialized = new SerializedObject(component);
                SerializedProperty iterator = serialized.GetIterator();
                bool enterChildren = true;
                while (iterator.NextVisible(enterChildren))
                {
                    enterChildren = false;
                    if (iterator.propertyType == SerializedPropertyType.ObjectReference &&
                        iterator.objectReferenceValue == null &&
                        iterator.objectReferenceInstanceIDValue != 0)
                    {
                        missing++;
                    }
                }
            }

            return missing;
        }

        private static void CreatePreviewScene()
        {
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PreviewPrefabPath);
            if (prefab == null)
            {
                throw new FileNotFoundException("Preview fire prefab was not found.", PreviewPrefabPath);
            }

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            instance.name = "Fire_Flame_03";
            instance.transform.position = Vector3.zero;

            var environment = new GameObject("PreviewEnvironment");
            Material floorMaterial = CreateFloorMaterial();
            GameObject floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.SetParent(environment.transform, false);
            floor.transform.localScale = new Vector3(1.2f, 1f, 1.2f);
            floor.GetComponent<MeshRenderer>().sharedMaterial = floorMaterial;

            Light key = new GameObject("KeyLight").AddComponent<Light>();
            key.type = LightType.Directional;
            key.color = new Color(1f, 0.76f, 0.55f);
            key.intensity = 65000f;
            key.transform.rotation = Quaternion.Euler(50f, -35f, 0f);
            if (key.GetComponent<HDAdditionalLightData>() == null)
            {
                key.gameObject.AddComponent<HDAdditionalLightData>();
            }

            Camera camera = new GameObject("PreviewCamera").AddComponent<Camera>();
            HDAdditionalCameraData cameraData = camera.GetComponent<HDAdditionalCameraData>();
            if (cameraData == null)
            {
                cameraData = camera.gameObject.AddComponent<HDAdditionalCameraData>();
            }

            cameraData.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
            cameraData.backgroundColorHDR = new Color(0.012f, 0.015f, 0.022f, 1f);

            camera.transform.position = new Vector3(2.1f, 1.25f, -3.2f);
            camera.transform.LookAt(new Vector3(0f, 0.72f, 0f));
            camera.fieldOfView = 34f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.012f, 0.015f, 0.022f);
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 40f;

            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
        }

        private static Material CreateFloorMaterial()
        {
            string path = MaterialFolder + "/FirePreview_Floor.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            Shader shader = Shader.Find("HDRP/Lit");
            if (shader == null)
            {
                throw new InvalidOperationException("HDRP/Lit shader is unavailable.");
            }

            if (material == null)
            {
                material = new Material(shader) { name = "FirePreview_Floor" };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
            }

            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", new Color(0.035f, 0.04f, 0.05f));
            }

            if (material.HasProperty("_Metallic")) material.SetFloat("_Metallic", 0.05f);
            if (material.HasProperty("_Smoothness")) material.SetFloat("_Smoothness", 0.35f);
            EditorUtility.SetDirty(material);
            return material;
        }

        private static void WriteReport(ValidationResult validation, HDRenderPipelineAsset pipeline, string renderStatus)
        {
            var report = new StringBuilder();
            report.AppendLine("# Fire Asset Validation");
            report.AppendLine();
            report.AppendLine($"- Source: `{FlameRoot}`");
            report.AppendLine($"- HDRP asset: `{PipelinePath}`");
            report.AppendLine($"- Active pipeline: `{pipeline?.name ?? "None"}`");
            report.AppendLine($"- Prefabs: {validation.PrefabCount}");
            report.AppendLine($"- VFX Graph assets: {validation.VfxGraphCount}");
            report.AppendLine($"- VisualEffect components: {validation.VisualEffectComponentCount}");
            report.AppendLine($"- Missing object references: {validation.MissingReferenceCount}");
            report.AppendLine($"- Validation errors: {validation.Errors.Count}");
            report.AppendLine($"- Preview scene: `{ScenePath}`");
            report.AppendLine($"- Preview image: `{PreviewPath}`");
            report.AppendLine($"- Render status: {renderStatus}");

            if (validation.Errors.Count > 0)
            {
                report.AppendLine();
                report.AppendLine("## Errors");
                foreach (string error in validation.Errors)
                {
                    report.AppendLine($"- {error}");
                }
            }

            File.WriteAllText(Path.GetFullPath(ReportPath), report.ToString(), Encoding.UTF8);
        }

        private static void EnsureFolders()
        {
            EnsureFolder(RootFolder);
            EnsureFolder(RenderingFolder);
            EnsureFolder(RootFolder + "/Materials");
            EnsureFolder(MaterialFolder);
            EnsureFolder(SceneFolder);
            EnsureFolder(PreviewFolder);
            EnsureFolder(ReportFolder);
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            string folder = Path.GetFileName(path);
            if (!string.IsNullOrEmpty(parent)) EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, folder);
        }

        private sealed class ValidationResult
        {
            public int PrefabCount;
            public int VfxGraphCount;
            public int VisualEffectComponentCount;
            public int MissingReferenceCount;
            public readonly List<string> Errors = new List<string>();
        }
    }
}
