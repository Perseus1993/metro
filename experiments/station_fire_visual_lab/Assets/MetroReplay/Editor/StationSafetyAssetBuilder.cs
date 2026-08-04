using System;
using System.IO;
using MetroReplay.Presentation;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace MetroReplay.Editor
{
    public static class StationSafetyAssetBuilder
    {
        private const string SourceRoot =
            "Assets/HazardVisualLab/ThirdParty/OpenGameArtTrafficRoadAssets/Models";
        private const string GeneratedRoot =
            "Assets/Resources/StationOperations";
        private const string MaterialRoot = GeneratedRoot + "/Materials";
        private const string PrefabRoot = GeneratedRoot + "/Prefabs";

        [MenuItem("Hazard Visual Lab/Build Station Safety Assets")]
        public static void EnsureBuilt()
        {
            Directory.CreateDirectory(MaterialRoot);
            Directory.CreateDirectory(PrefabRoot);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

            BuildWaterBarrier(
                "Plastic_Road_Block.fbx",
                "WaterBarrier_Red.prefab",
                new Color(0.78f, 0.055f, 0.025f));
            BuildWaterBarrier(
                "Plastic_Road_Block_001.fbx",
                "WaterBarrier_Yellow.prefab",
                new Color(0.92f, 0.52f, 0.015f));

            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            Debug.Log("STATION_SAFETY_ASSETS_BUILT=WATER_BARRIERS=2;LICENCE=CC0");
        }

        public static void InspectBuiltAssets()
        {
            foreach (var assetName in new[] { "WaterBarrier_Red", "WaterBarrier_Yellow" })
            {
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(
                    PrefabRoot + "/" + assetName + ".prefab");
                if (prefab == null)
                    throw new FileNotFoundException("Generated prefab is missing: " + assetName);
                var instance = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
                try
                {
                    var bounds = default(Bounds);
                    var found = false;
                    foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
                    {
                        bounds = found ? Encapsulate(bounds, renderer.bounds) : renderer.bounds;
                        found = true;
                        var mesh = renderer is MeshRenderer
                            ? renderer.GetComponent<MeshFilter>()?.sharedMesh
                            : (renderer as SkinnedMeshRenderer)?.sharedMesh;
                        var color = renderer.sharedMaterial != null
                                    && renderer.sharedMaterial.HasProperty("_BaseColor")
                            ? renderer.sharedMaterial.GetColor("_BaseColor").ToString("F3")
                            : "none";
                        Debug.Log(
                            $"STATION_SAFETY_RENDERER={assetName};NAME={renderer.name};MESH={mesh?.name};" +
                            $"VERTICES={mesh?.vertexCount ?? 0};MATERIAL={renderer.sharedMaterial?.name};COLOR={color}");
                    }
                    Debug.Log($"STATION_SAFETY_BOUNDS={assetName};SIZE={bounds.size:F3};CENTER={bounds.center:F3}");
                }
                finally
                {
                    if (instance != null)
                        UnityEngine.Object.DestroyImmediate(instance);
                }
            }
        }

        private static Bounds Encapsulate(Bounds left, Bounds right)
        {
            left.Encapsulate(right);
            return left;
        }

        private static void BuildWaterBarrier(
            string sourceFilename,
            string prefabFilename,
            Color color)
        {
            var sourcePath = SourceRoot + "/" + sourceFilename;
            ConfigureModelImporter(sourcePath);
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(sourcePath);
            if (source == null)
                throw new FileNotFoundException("Water-barrier source model is missing.", sourcePath);

            var material = BuildMaterial(
                MaterialRoot + "/" + Path.GetFileNameWithoutExtension(prefabFilename) + ".mat",
                color);
            var instance = PrefabUtility.InstantiatePrefab(source) as GameObject;
            if (instance == null)
                throw new InvalidOperationException("Could not instantiate " + sourcePath);

            try
            {
                instance.name = Path.GetFileNameWithoutExtension(prefabFilename);
                foreach (var collider in instance.GetComponentsInChildren<Collider>(true))
                    UnityEngine.Object.DestroyImmediate(collider);
                foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
                {
                    var count = Mathf.Max(1, renderer.sharedMaterials.Length);
                    var materials = new Material[count];
                    for (var index = 0; index < count; index++)
                        materials[index] = material;
                    renderer.sharedMaterials = materials;
                    renderer.shadowCastingMode = ShadowCastingMode.On;
                    renderer.receiveShadows = true;
                }
                instance.AddComponent<VisualOnlyStationAssetIdentity>().Configure(
                    Path.GetFileNameWithoutExtension(prefabFilename),
                    "OpenGameArt Traffic Road Assets by MilkAndBanana",
                    "CC0-1.0");
                PrefabUtility.SaveAsPrefabAsset(instance, PrefabRoot + "/" + prefabFilename);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        private static void ConfigureModelImporter(string path)
        {
            var importer = AssetImporter.GetAtPath(path) as ModelImporter;
            if (importer == null)
                return;
            importer.importAnimation = false;
            importer.importCameras = false;
            importer.importLights = false;
            importer.addCollider = false;
            importer.materialImportMode = ModelImporterMaterialImportMode.None;
            importer.isReadable = false;
            importer.SaveAndReimport();
        }

        private static Material BuildMaterial(string path, Color color)
        {
            var shader = Shader.Find("HDRP/Lit") ?? Shader.Find("Standard");
            if (shader == null)
                throw new InvalidOperationException("No compatible lit shader is available.");

            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(shader);
                AssetDatabase.CreateAsset(material, path);
            }
            material.name = Path.GetFileNameWithoutExtension(path);
            material.shader = shader;
            material.enableInstancing = true;
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
            if (material.HasProperty("_Metallic"))
                material.SetFloat("_Metallic", 0.02f);
            if (material.HasProperty("_Smoothness"))
                material.SetFloat("_Smoothness", 0.28f);
            if (shader.name == "HDRP/Lit")
            {
                if (material.HasProperty("_SurfaceType"))
                    material.SetFloat("_SurfaceType", 0f);
                if (material.HasProperty("_AlphaCutoffEnable"))
                    material.SetFloat("_AlphaCutoffEnable", 0f);
                if (material.HasProperty("_ZWrite"))
                    material.SetFloat("_ZWrite", 1f);
                HDMaterial.ValidateMaterial(material);
            }
            EditorUtility.SetDirty(material);
            return material;
        }
    }
}
