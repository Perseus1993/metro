using System;
using System.IO;
using System.Linq;
using MetroReplay.Presentation;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using UnityMeshSimplifier;

namespace MetroReplay.Editor
{
    public static class RocketboxPassengerPrefabBuilder
    {
        private const string SourceRoot = "Assets/Resources/PassengerBases/Rocketbox";
        private const string GeneratedRoot = "Assets/Resources/PassengerBases/Generated";
        internal const string MaterialFolder = GeneratedRoot + "/Materials";
        private const string MeshFolder = GeneratedRoot + "/Meshes";
        private const string PrefabFolder = GeneratedRoot + "/Prefabs";
        private const string ControllerPath = GeneratedRoot + "/RocketboxPassenger.controller";

        private static readonly string[] Models =
        {
            "Female_Adult_01", "Female_Adult_05",
            "Female_Adult_10", "Male_Adult_03",
            "Male_Adult_08", "Male_Adult_14",
            "Business_Female_01", "Business_Male_02"
        };

        [MenuItem("Metro Replay/Build Rocketbox Passenger Library")]
        public static void EnsureBuilt()
        {
            EnsureFolders();
            AssetDatabase.Refresh();
            var controller = BuildController();
            foreach (var relativePath in Models)
                BuildPrefab(relativePath, controller);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log($"ROCKETBOX_LIBRARY_BUILT=BASES={Models.Length};LOD_LEVELS=3");
        }

        private static void BuildPrefab(string relativePath, RuntimeAnimatorController controller)
        {
            var baseName = relativePath.Split('/').Last();
            var modelPath = $"{SourceRoot}/{relativePath}/Export/{baseName}.fbx";
            var source = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            if (source == null)
                throw new FileNotFoundException("Rocketbox model is missing.", modelPath);
            var root = (GameObject)PrefabUtility.InstantiatePrefab(source);
            root.name = baseName;
            try
            {
                ConfigureAnimator(root, controller);
                var high = root.GetComponentInChildren<SkinnedMeshRenderer>(true);
                if (high == null)
                    throw new InvalidOperationException($"{baseName} has no skinned mesh renderer.");
                high.sharedMaterials = RocketboxMaterialBuilder.Build(
                    baseName, modelPath, high.sharedMaterials);
                var mid = CreateLodRenderer(high, baseName, "Mid", 0.50f);
                var low = CreateLodRenderer(high, baseName, "Low", 0.18f);
                ConfigureLodGroup(root, high, mid, low);
                root.AddComponent<PassengerBaseIdentity>().Configure(baseName, 3);
                PrefabUtility.SaveAsPrefabAsset(root, $"{PrefabFolder}/{baseName}.prefab");
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        private static SkinnedMeshRenderer CreateLodRenderer(
            SkinnedMeshRenderer source,
            string baseName,
            string suffix,
            float quality)
        {
            var child = new GameObject($"{baseName}_{suffix}");
            child.transform.SetParent(source.transform.parent, false);
            var renderer = child.AddComponent<SkinnedMeshRenderer>();
            renderer.sharedMesh = BuildMesh(source.sharedMesh, baseName, suffix, quality);
            renderer.sharedMaterials = source.sharedMaterials;
            renderer.bones = source.bones;
            renderer.rootBone = source.rootBone;
            renderer.localBounds = source.localBounds;
            renderer.quality = SkinQuality.Auto;
            renderer.updateWhenOffscreen = false;
            return renderer;
        }

        private static Mesh BuildMesh(Mesh source, string baseName, string suffix, float quality)
        {
            var simplifier = new MeshSimplifier();
            simplifier.Initialize(source);
            simplifier.SimplifyMesh(quality);
            var mesh = simplifier.ToMesh();
            mesh.name = $"{baseName}_{suffix}_{Mathf.RoundToInt(quality * 100f)}";
            mesh.RecalculateBounds();
            var path = $"{MeshFolder}/{mesh.name}.asset";
            AssetDatabase.DeleteAsset(path);
            AssetDatabase.CreateAsset(mesh, path);
            return mesh;
        }

        private static void ConfigureLodGroup(
            GameObject root,
            Renderer high,
            Renderer mid,
            Renderer low)
        {
            var group = root.AddComponent<LODGroup>();
            group.fadeMode = LODFadeMode.CrossFade;
            group.animateCrossFading = true;
            group.SetLODs(new[]
            {
                new LOD(0.16f, new[] { high }),
                new LOD(0.065f, new[] { mid }),
                new LOD(0.012f, new[] { low })
            });
            group.RecalculateBounds();
        }

        private static void ConfigureAnimator(GameObject root, RuntimeAnimatorController controller)
        {
            var animator = root.GetComponent<Animator>() ?? root.AddComponent<Animator>();
            animator.runtimeAnimatorController = controller;
            animator.applyRootMotion = false;
            animator.cullingMode = AnimatorCullingMode.CullUpdateTransforms;
        }

        private static RuntimeAnimatorController BuildController()
        {
            AssetDatabase.DeleteAsset(ControllerPath);
            var controller = AnimatorController.CreateAnimatorControllerAtPath(ControllerPath);
            var machine = controller.layers[0].stateMachine;
            AddState(machine, "Idle_Loop", "m_idle_neutral_01.max.fbx");
            AddState(machine, "Walk_Loop", "m_walk_neutral_01.max.fbx");
            AddState(machine, "Jog_Fwd_Loop", "m_run_neutral.max.fbx");
            return controller;
        }

        private static void AddState(AnimatorStateMachine machine, string name, string fileName)
        {
            var path = $"{SourceRoot}Animations/{fileName}";
            var clip = AssetDatabase.LoadAllAssetsAtPath(path)
                .OfType<AnimationClip>()
                .FirstOrDefault(item => !item.name.StartsWith("__preview__", StringComparison.Ordinal));
            if (clip == null)
                throw new FileNotFoundException($"Animation {name} is missing.", path);
            var state = machine.AddState(name);
            state.motion = clip;
            if (name == "Idle_Loop")
                machine.defaultState = state;
        }

        private static void EnsureFolders()
        {
            Directory.CreateDirectory(MaterialFolder);
            Directory.CreateDirectory(MeshFolder);
            Directory.CreateDirectory(PrefabFolder);
        }
    }
}
