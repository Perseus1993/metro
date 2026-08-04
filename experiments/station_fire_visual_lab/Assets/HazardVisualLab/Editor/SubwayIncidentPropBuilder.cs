using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace HazardVisualLab.EditorTools
{
    public static class SubwayIncidentPropBuilder
    {
        private const string Root =
            "Assets/HazardVisualLab/ThirdParty/SubwayIncidentProps";
        private const string ModelRoot = Root + "/Raw/Models";
        private const string TextureRoot = Root + "/Raw/Textures";
        private const string MaterialRoot = Root + "/Materials";
        private const string PrefabRoot = Root + "/Prefabs";
        private const string SparkSourceRoot = Root + "/ElectricalSparks/Source";

        [MenuItem("Hazard Visual Lab/Build Subway Incident Prop Catalog")]
        public static void BuildAll()
        {
            try
            {
                Directory.CreateDirectory(MaterialRoot);
                Directory.CreateDirectory(PrefabRoot);
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

                ConfigureTextureImporters();

                var bin = BuildLitMaterial(
                    "MI_Bin_HDRP",
                    "TX_Bin_01a_ALB.png",
                    "TX_Bin_01a_NRM.png",
                    null,
                    new Color(0.74f, 0.76f, 0.77f),
                    0.62f,
                    0.48f);
                var cabinet = BuildLitMaterial(
                    "MI_FireExtinguisherCabinet_HDRP",
                    "TX_Fire_Extinguisher_Cabinet_01a_ALB.png",
                    "TX_Fire_Extinguisher_Cabinet_01a_NRM.png",
                    null,
                    Color.white,
                    0.58f,
                    0.52f);
                var helpMachine = BuildLitMaterial(
                    "MI_HelpMachine_HDRP",
                    null,
                    null,
                    null,
                    new Color(0.035f, 0.18f, 0.42f),
                    0.42f,
                    0.66f);
                var vending = BuildLitMaterial(
                    "MI_VendingMachine_HDRP",
                    "TX_Vending_Machine_01a_ALB.png",
                    "TX_Vending_Machine_01a_NRM.png",
                    "TX_Vending_Machine_01a_EMM.png",
                    Color.white,
                    0.34f,
                    0.58f);

                BuildModelPrefab(
                    "SM_Bin_01a.fbx",
                    "PF_Bin_01a_HDRP.prefab",
                    bin);
                BuildModelPrefab(
                    "SM_Fire_Extinguisher_Cabinet_01a.fbx",
                    "PF_FireExtinguisherCabinet_01a_HDRP.prefab",
                    cabinet);
                BuildModelPrefab(
                    "SM_Help_machine_01a.fbx",
                    "PF_HelpMachine_01a_HDRP.prefab",
                    helpMachine);
                BuildModelPrefab(
                    "SM_Vending_Machine_01a.fbx",
                    "PF_VendingMachine_01a_HDRP.prefab",
                    vending);
                BuildModelPrefab(
                    "SM_Vending_Machine_01b.fbx",
                    "PF_VendingMachine_01b_HDRP.prefab",
                    vending);
                BuildElectricalSparks();

                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                ValidateCatalog();
                Debug.Log("[HazardVisualLab] Subway incident prop catalog built: " + PrefabRoot);
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                if (Application.isBatchMode)
                    EditorApplication.Exit(1);
                throw;
            }

            if (Application.isBatchMode)
                EditorApplication.Exit(0);
        }

        private static void ConfigureTextureImporters()
        {
            var textureGuids = AssetDatabase.FindAssets("t:Texture2D", new[] { TextureRoot });
            foreach (var guid in textureGuids)
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (AssetImporter.GetAtPath(path) is not TextureImporter importer)
                    continue;

                var filename = Path.GetFileNameWithoutExtension(path);
                var changed = false;
                if (filename.EndsWith("_NRM", StringComparison.OrdinalIgnoreCase)
                    && importer.textureType != TextureImporterType.NormalMap)
                {
                    importer.textureType = TextureImporterType.NormalMap;
                    changed = true;
                }
                else if (filename.EndsWith("_RMA", StringComparison.OrdinalIgnoreCase)
                         || filename.EndsWith("_AO", StringComparison.OrdinalIgnoreCase)
                         || filename.EndsWith("_M", StringComparison.OrdinalIgnoreCase)
                         || filename.EndsWith("_R", StringComparison.OrdinalIgnoreCase))
                {
                    if (importer.sRGBTexture)
                    {
                        importer.sRGBTexture = false;
                        changed = true;
                    }
                }

                if (changed)
                    importer.SaveAndReimport();
            }
        }

        private static Material BuildLitMaterial(
            string name,
            string albedoName,
            string normalName,
            string emissiveName,
            Color baseColor,
            float metallic,
            float smoothness)
        {
            var shader = Shader.Find("HDRP/Lit")
                ?? throw new InvalidOperationException("HDRP/Lit shader is unavailable.");
            var path = $"{MaterialRoot}/{name}.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (material == null)
            {
                material = new Material(shader) { name = name };
                AssetDatabase.CreateAsset(material, path);
            }
            else
            {
                material.shader = shader;
            }

            material.SetColor("_BaseColor", baseColor);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Smoothness", smoothness);

            var albedo = LoadTexture(albedoName);
            if (albedo != null)
            {
                material.SetTexture("_BaseColorMap", albedo);
                material.mainTexture = albedo;
            }

            var normal = LoadTexture(normalName);
            if (normal != null)
            {
                material.SetTexture("_NormalMap", normal);
                material.SetFloat("_NormalScale", 1f);
                material.EnableKeyword("_NORMALMAP_TANGENT_SPACE");
            }

            var emissive = LoadTexture(emissiveName);
            if (emissive != null)
            {
                material.SetTexture("_EmissiveColorMap", emissive);
                material.SetColor("_EmissiveColor", Color.white * 1.35f);
                material.EnableKeyword("_EMISSIVE_COLOR_MAP");
                material.EnableKeyword("_EMISSION");
                material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            }

            HDMaterial.ValidateMaterial(material);
            EditorUtility.SetDirty(material);
            return material;
        }

        private static Texture2D LoadTexture(string filename)
        {
            return string.IsNullOrEmpty(filename)
                ? null
                : AssetDatabase.LoadAssetAtPath<Texture2D>($"{TextureRoot}/{filename}");
        }

        private static void BuildModelPrefab(
            string modelFilename,
            string prefabFilename,
            Material material)
        {
            var modelPath = $"{ModelRoot}/{modelFilename}";
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            if (model == null)
                throw new FileNotFoundException("Imported model is unavailable.", modelPath);

            var root = new GameObject(Path.GetFileNameWithoutExtension(prefabFilename));
            try
            {
                var visual = PrefabUtility.InstantiatePrefab(model) as GameObject;
                if (visual == null)
                    throw new InvalidOperationException("Could not instantiate model: " + modelPath);
                visual.name = "Visual";
                visual.transform.SetParent(root.transform, false);
                visual.transform.localPosition = Vector3.zero;
                visual.transform.localRotation = Quaternion.identity;

                var renderers = visual.GetComponentsInChildren<Renderer>(true);
                foreach (var renderer in renderers)
                {
                    var slots = Mathf.Max(1, renderer.sharedMaterials.Length);
                    var materials = new Material[slots];
                    for (var index = 0; index < slots; index++)
                        materials[index] = material;
                    renderer.sharedMaterials = materials;
                }

                AddBoundsCollider(root, renderers);
                PrefabUtility.SaveAsPrefabAsset(root, $"{PrefabRoot}/{prefabFilename}");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static void AddBoundsCollider(GameObject root, IReadOnlyList<Renderer> renderers)
        {
            var initialized = false;
            var bounds = new Bounds();
            foreach (var renderer in renderers)
            {
                if (!initialized)
                {
                    bounds = renderer.bounds;
                    initialized = true;
                }
                else
                {
                    bounds.Encapsulate(renderer.bounds);
                }
            }

            if (!initialized)
                return;
            var collider = root.AddComponent<BoxCollider>();
            collider.center = root.transform.InverseTransformPoint(bounds.center);
            collider.size = bounds.size;
        }

        private static void BuildElectricalSparks()
        {
            var shader = Shader.Find("HDRP/Unlit")
                ?? throw new InvalidOperationException("HDRP/Unlit shader is unavailable.");
            var texturePath = SparkSourceRoot + "/Textures/SparkParticle.png";
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath)
                ?? throw new FileNotFoundException("Spark texture is unavailable.", texturePath);
            var materialPath = MaterialRoot + "/MI_ElectricalSparks_HDRP.mat";
            var material = AssetDatabase.LoadAssetAtPath<Material>(materialPath);
            if (material == null)
            {
                material = new Material(shader) { name = "MI_ElectricalSparks_HDRP" };
                AssetDatabase.CreateAsset(material, materialPath);
            }
            else
            {
                material.shader = shader;
            }

            material.SetTexture("_UnlitColorMap", texture);
            material.SetColor("_UnlitColor", new Color(1f, 0.58f, 0.16f, 0.92f));
            material.SetColor("_EmissiveColor", new Color(7.2f, 2.7f, 0.55f, 1f));
            material.SetFloat("_SurfaceType", 1f);
            material.SetFloat("_BlendMode", 1f);
            material.SetInt("_SrcBlend", (int)BlendMode.One);
            material.SetInt("_DstBlend", (int)BlendMode.One);
            material.SetInt("_ZWrite", 0);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.EnableKeyword("_EMISSION");
            material.renderQueue = 3000;
            HDMaterial.ValidateMaterial(material);
            EditorUtility.SetDirty(material);

            var sourcePath = SparkSourceRoot + "/ElectricalSparks.prefab";
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(sourcePath)
                ?? throw new FileNotFoundException("Electrical sparks source prefab is unavailable.", sourcePath);
            var instance = PrefabUtility.InstantiatePrefab(source) as GameObject;
            if (instance == null)
                throw new InvalidOperationException("Could not instantiate electrical sparks prefab.");
            try
            {
                instance.name = "PF_ElectricalSparks_HDRP";
                instance.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
                instance.transform.localScale = Vector3.one;
                foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
                {
                    var slots = Mathf.Max(1, renderer.sharedMaterials.Length);
                    var materials = new Material[slots];
                    for (var index = 0; index < slots; index++)
                        materials[index] = material;
                    renderer.sharedMaterials = materials;
                }
                PrefabUtility.SaveAsPrefabAsset(
                    instance,
                    PrefabRoot + "/PF_ElectricalSparks_HDRP.prefab");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        private static void ValidateCatalog()
        {
            var expected = new[]
            {
                "PF_Bin_01a_HDRP.prefab",
                "PF_FireExtinguisherCabinet_01a_HDRP.prefab",
                "PF_HelpMachine_01a_HDRP.prefab",
                "PF_VendingMachine_01a_HDRP.prefab",
                "PF_VendingMachine_01b_HDRP.prefab",
                "PF_ElectricalSparks_HDRP.prefab"
            };
            foreach (var filename in expected)
            {
                var path = $"{PrefabRoot}/{filename}";
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null)
                    throw new InvalidOperationException("Generated prefab validation failed: " + path);

                var renderers = prefab.GetComponentsInChildren<Renderer>(true);
                if (renderers.Length == 0)
                    throw new InvalidOperationException("Generated prefab has no renderer: " + path);
                foreach (var renderer in renderers)
                {
                    foreach (var material in renderer.sharedMaterials)
                    {
                        if (material == null || material.shader == null)
                            throw new InvalidOperationException("Generated prefab has a missing material: " + path);
                        if (!material.shader.name.StartsWith("HDRP/", StringComparison.Ordinal))
                            throw new InvalidOperationException(
                                $"Generated prefab uses a non-HDRP shader ({material.shader.name}): {path}");
                    }
                }

                if (!filename.Contains("ElectricalSparks", StringComparison.Ordinal)
                    && prefab.GetComponent<BoxCollider>() == null)
                {
                    throw new InvalidOperationException("Generated prop prefab has no bounds collider: " + path);
                }
            }

            var sparksPath = PrefabRoot + "/PF_ElectricalSparks_HDRP.prefab";
            var sparks = AssetDatabase.LoadAssetAtPath<GameObject>(sparksPath);
            if (sparks.GetComponentsInChildren<ParticleSystem>(true).Length == 0)
                throw new InvalidOperationException("Electrical sparks prefab has no particle system.");
        }
    }
}
