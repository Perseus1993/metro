using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using Object = UnityEngine.Object;

namespace HazardAssetLab.EditorTools
{
    public static class GenerateHotelDeliveryRobot
    {
        private const string RootFolder = "Assets/HazardAssetLab";
        private const string MaterialFolder = RootFolder + "/Materials/GenericHotelDeliveryRobot";
        private const string PrefabFolder = RootFolder + "/Prefabs";
        private const string SceneFolder = RootFolder + "/Scenes";
        private const string PreviewFolder = RootFolder + "/Previews";
        private const string PrefabPath = PrefabFolder + "/GenericHotelDeliveryRobot.prefab";
        private const string ScenePath = SceneFolder + "/RobotAssetPreview.unity";
        private const string PreviewPath = PreviewFolder + "/GenericHotelDeliveryRobot.png";

        [MenuItem("Hazard Asset Lab/Generate Free Hotel Delivery Robot")]
        public static void Build()
        {
            try
            {
                EnsureFolders();

                Material shell = CreateMaterial("Robot_Shell", new Color(0.91f, 0.94f, 0.96f), 0.12f, 0.72f);
                Material trim = CreateMaterial("Robot_Trim", new Color(0.055f, 0.075f, 0.095f), 0.22f, 0.58f);
                Material cargo = CreateMaterial("Robot_CargoDoor", new Color(0.085f, 0.12f, 0.15f), 0.28f, 0.62f);
                Material rubber = CreateMaterial("Robot_Rubber", new Color(0.025f, 0.03f, 0.035f), 0.0f, 0.28f);
                Material screen = CreateMaterial("Robot_Screen", new Color(0.012f, 0.025f, 0.035f), 0.18f, 0.8f);
                Material cyan = CreateMaterial("Robot_LED_Cyan", new Color(0.02f, 0.33f, 0.48f), 0.05f, 0.7f, new Color(0.02f, 2.5f, 4.2f));
                Material blue = CreateMaterial("Robot_Accent_Blue", new Color(0.03f, 0.24f, 0.42f), 0.18f, 0.66f);

                GameObject robot = CreateRobot(shell, trim, cargo, rubber, screen, cyan, blue);
                GameObject prefab = PrefabUtility.SaveAsPrefabAsset(robot, PrefabPath);
                AssetDatabase.SetLabels(prefab, new[] { "hazard-lab", "free", "hotel-delivery-robot", "original" });

                int triangles = CountTriangles(robot);
                Object.DestroyImmediate(robot);

                CreatePreviewScene(prefab, shell, trim, cyan);
                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();

                Debug.Log($"[HazardAssetLab] Generated original free hotel delivery robot. Prefab={PrefabPath}, triangles={triangles}, preview={PreviewPath}");
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

        private static GameObject CreateRobot(Material shell, Material trim, Material cargo, Material rubber, Material screen, Material cyan, Material blue)
        {
            var root = new GameObject("GenericHotelDeliveryRobot");

            BoxCollider collider = root.AddComponent<BoxCollider>();
            collider.center = new Vector3(0f, 0.82f, 0f);
            collider.size = new Vector3(0.82f, 1.62f, 0.7f);

            // Concealed mobile base and a bright status band.
            AddPrimitive(root.transform, "BaseShell", PrimitiveType.Sphere, new Vector3(0f, 0.2f, 0.02f), new Vector3(0.8f, 0.31f, 0.69f), Vector3.zero, shell);
            AddPrimitive(root.transform, "BaseTrim", PrimitiveType.Cylinder, new Vector3(0f, 0.125f, 0.02f), new Vector3(0.73f, 0.035f, 0.62f), Vector3.zero, trim);
            AddPrimitive(root.transform, "StatusLightRing", PrimitiveType.Cylinder, new Vector3(0f, 0.17f, 0.02f), new Vector3(0.77f, 0.018f, 0.66f), Vector3.zero, cyan);

            AddWheel(root.transform, "Wheel_FL", new Vector3(-0.29f, 0.07f, -0.16f), rubber);
            AddWheel(root.transform, "Wheel_FR", new Vector3(0.29f, 0.07f, -0.16f), rubber);
            AddWheel(root.transform, "Wheel_RL", new Vector3(-0.29f, 0.07f, 0.18f), rubber);
            AddWheel(root.transform, "Wheel_RR", new Vector3(0.29f, 0.07f, 0.18f), rubber);

            // One enclosed rounded delivery pod: no exposed restaurant trays.
            AddPrimitive(root.transform, "CargoPodShell", PrimitiveType.Capsule, new Vector3(0f, 0.83f, 0.025f), new Vector3(0.72f, 0.6f, 0.62f), Vector3.zero, shell);
            AddPrimitive(root.transform, "LowerBodyBelt", PrimitiveType.Cylinder, new Vector3(0f, 0.36f, 0.025f), new Vector3(0.68f, 0.018f, 0.58f), Vector3.zero, blue);

            // A single sealed cargo door reads as one bucket/compartment.
            AddPrimitive(root.transform, "CargoDoorOuter", PrimitiveType.Sphere, new Vector3(0f, 0.72f, -0.293f), new Vector3(0.5f, 0.57f, 0.04f), Vector3.zero, trim);
            AddPrimitive(root.transform, "CargoDoorInset", PrimitiveType.Sphere, new Vector3(0f, 0.72f, -0.317f), new Vector3(0.43f, 0.5f, 0.025f), Vector3.zero, cargo);
            AddPrimitive(root.transform, "CargoDoorHandle", PrimitiveType.Cube, new Vector3(0f, 0.83f, -0.336f), new Vector3(0.16f, 0.022f, 0.012f), Vector3.zero, cyan);
            AddPrimitive(root.transform, "CargoDoorStatus", PrimitiveType.Sphere, new Vector3(0f, 0.49f, -0.336f), new Vector3(0.035f, 0.035f, 0.014f), Vector3.zero, cyan);

            // Integrated friendly screen on the same pod body.
            AddPrimitive(root.transform, "FaceScreen", PrimitiveType.Sphere, new Vector3(0f, 1.19f, -0.292f), new Vector3(0.45f, 0.17f, 0.038f), Vector3.zero, screen);
            AddPrimitive(root.transform, "LeftEye", PrimitiveType.Cube, new Vector3(-0.094f, 1.212f, -0.314f), new Vector3(0.064f, 0.024f, 0.01f), new Vector3(4f, 0f, -8f), cyan);
            AddPrimitive(root.transform, "RightEye", PrimitiveType.Cube, new Vector3(0.094f, 1.212f, -0.314f), new Vector3(0.064f, 0.024f, 0.01f), new Vector3(4f, 0f, 8f), cyan);
            AddPrimitive(root.transform, "Smile", PrimitiveType.Cube, new Vector3(0f, 1.163f, -0.314f), new Vector3(0.1f, 0.012f, 0.01f), new Vector3(4f, 0f, 0f), cyan);

            // Compact top navigation puck.
            AddPrimitive(root.transform, "TopLidar", PrimitiveType.Cylinder, new Vector3(0f, 1.46f, 0.025f), new Vector3(0.17f, 0.035f, 0.17f), Vector3.zero, trim);
            AddPrimitive(root.transform, "TopLidarLight", PrimitiveType.Cylinder, new Vector3(0f, 1.502f, 0.025f), new Vector3(0.12f, 0.008f, 0.12f), Vector3.zero, cyan);

            AddPrimitive(root.transform, "FrontSensorBar", PrimitiveType.Sphere, new Vector3(0f, 0.235f, -0.318f), new Vector3(0.19f, 0.065f, 0.032f), Vector3.zero, trim);
            AddPrimitive(root.transform, "FrontSensorLeft", PrimitiveType.Sphere, new Vector3(-0.045f, 0.235f, -0.336f), new Vector3(0.024f, 0.024f, 0.014f), Vector3.zero, cyan);
            AddPrimitive(root.transform, "FrontSensorRight", PrimitiveType.Sphere, new Vector3(0.045f, 0.235f, -0.336f), new Vector3(0.024f, 0.024f, 0.014f), Vector3.zero, cyan);

            return root;
        }

        private static void AddWheel(Transform parent, string name, Vector3 position, Material material)
        {
            AddPrimitive(parent, name, PrimitiveType.Cylinder, position, new Vector3(0.075f, 0.026f, 0.075f), new Vector3(0f, 0f, 90f), material);
        }

        private static GameObject AddPrimitive(Transform parent, string name, PrimitiveType type, Vector3 localPosition, Vector3 localScale, Vector3 localEuler, Material material)
        {
            GameObject gameObject = GameObject.CreatePrimitive(type);
            gameObject.name = name;
            gameObject.transform.SetParent(parent, false);
            gameObject.transform.localPosition = localPosition;
            gameObject.transform.localEulerAngles = localEuler;
            gameObject.transform.localScale = localScale;

            Collider primitiveCollider = gameObject.GetComponent<Collider>();
            if (primitiveCollider != null)
            {
                Object.DestroyImmediate(primitiveCollider);
            }

            gameObject.GetComponent<MeshRenderer>().sharedMaterial = material;
            return gameObject;
        }

        private static Material CreateMaterial(string name, Color color, float metallic, float smoothness, Color? emission = null)
        {
            string path = $"{MaterialFolder}/{name}.mat";
            Material material = AssetDatabase.LoadAssetAtPath<Material>(path);
            Shader shader = FindCompatibleLitShader();

            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else if (material.shader != shader)
            {
                material.shader = shader;
            }

            SetColor(material, "_BaseColor", "_Color", color);
            SetFloat(material, "_Metallic", metallic);
            SetFloat(material, "_Smoothness", smoothness);
            SetFloat(material, "_Glossiness", smoothness);

            if (emission.HasValue)
            {
                material.EnableKeyword("_EMISSION");
                if (material.HasProperty("_EmissiveColor")) material.SetColor("_EmissiveColor", emission.Value);
                if (material.HasProperty("_EmissionColor")) material.SetColor("_EmissionColor", emission.Value);
                material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            }

            EditorUtility.SetDirty(material);
            return material;
        }

        private static Shader FindCompatibleLitShader()
        {
            RenderPipelineAsset pipeline = GraphicsSettings.currentRenderPipeline;
            if (pipeline == null)
            {
                return Shader.Find("Standard");
            }

            string pipelineName = pipeline.GetType().Name;
            if (pipelineName.IndexOf("HDRenderPipeline", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return Shader.Find("HDRP/Lit") ?? Shader.Find("Standard");
            }

            if (pipelineName.IndexOf("Universal", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                return Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            }

            return Shader.Find("Standard");
        }

        private static void SetColor(Material material, string preferred, string fallback, Color value)
        {
            if (material.HasProperty(preferred)) material.SetColor(preferred, value);
            else if (material.HasProperty(fallback)) material.SetColor(fallback, value);
        }

        private static void SetFloat(Material material, string property, float value)
        {
            if (material.HasProperty(property)) material.SetFloat(property, value);
        }

        private static void CreatePreviewScene(GameObject prefab, Material shell, Material trim, Material cyan)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            instance.transform.position = Vector3.zero;

            Material floorMaterial = CreateMaterial("Preview_Floor", new Color(0.06f, 0.075f, 0.09f), 0.05f, 0.5f);
            Material wallMaterial = CreateMaterial("Preview_Wall", new Color(0.16f, 0.19f, 0.22f), 0.02f, 0.32f);
            AddPrimitive(new GameObject("PreviewEnvironment").transform, "Floor", PrimitiveType.Cube, new Vector3(0f, -0.04f, 0f), new Vector3(4f, 0.08f, 4f), Vector3.zero, floorMaterial);
            AddPrimitive(GameObject.Find("PreviewEnvironment").transform, "Backdrop", PrimitiveType.Cube, new Vector3(0f, 1.45f, 1.55f), new Vector3(4f, 2.9f, 0.08f), Vector3.zero, wallMaterial);

            var key = new GameObject("KeyLight").AddComponent<Light>();
            key.type = LightType.Directional;
            key.color = new Color(0.88f, 0.93f, 1f);
            bool physicalLights = GraphicsSettings.currentRenderPipeline != null;
            key.intensity = physicalLights ? 65000f : 1.15f;
            key.transform.rotation = Quaternion.Euler(42f, -32f, 0f);

            var fill = new GameObject("FillLight").AddComponent<Light>();
            fill.type = LightType.Point;
            fill.range = 6f;
            fill.intensity = physicalLights ? 800f : 1.7f;
            fill.color = new Color(0.25f, 0.65f, 1f);
            fill.transform.position = new Vector3(-1.8f, 1.4f, -1.2f);

            var rim = new GameObject("RimLight").AddComponent<Light>();
            rim.type = LightType.Point;
            rim.range = 5f;
            rim.intensity = physicalLights ? 500f : 1.15f;
            rim.color = new Color(0.4f, 0.8f, 1f);
            rim.transform.position = new Vector3(1.5f, 1.8f, 1.1f);

            Camera camera = new GameObject("PreviewCamera").AddComponent<Camera>();
            camera.transform.position = new Vector3(2.25f, 1.65f, -2.85f);
            camera.transform.LookAt(new Vector3(0f, 0.82f, 0f));
            camera.fieldOfView = 34f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.035f, 0.045f, 0.06f);
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 40f;

            EditorSceneManager.SaveScene(scene, ScenePath);
            RenderPreview(camera, PreviewPath);
        }

        private static void RenderPreview(Camera camera, string assetPath)
        {
            const int size = 900;
            RenderTexture renderTexture = RenderTexture.GetTemporary(size, size, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
            RenderTexture previous = RenderTexture.active;
            camera.targetTexture = renderTexture;
            RenderTexture.active = renderTexture;

            camera.Render();
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, false, false);
            texture.ReadPixels(new Rect(0, 0, size, size), 0, 0);
            texture.Apply();

            string absolutePath = Path.GetFullPath(assetPath);
            File.WriteAllBytes(absolutePath, texture.EncodeToPNG());

            camera.targetTexture = null;
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(renderTexture);
            Object.DestroyImmediate(texture);
        }

        private static int CountTriangles(GameObject root)
        {
            int total = 0;
            foreach (MeshFilter filter in root.GetComponentsInChildren<MeshFilter>())
            {
                if (filter.sharedMesh != null)
                {
                    total += filter.sharedMesh.triangles.Length / 3;
                }
            }
            return total;
        }

        private static void EnsureFolders()
        {
            EnsureFolder(RootFolder);
            EnsureFolder(RootFolder + "/Editor");
            EnsureFolder(RootFolder + "/Materials");
            EnsureFolder(MaterialFolder);
            EnsureFolder(PrefabFolder);
            EnsureFolder(SceneFolder);
            EnsureFolder(PreviewFolder);
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            string folder = Path.GetFileName(path);
            if (!string.IsNullOrEmpty(parent)) EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, folder);
        }
    }
}
