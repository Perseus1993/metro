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
        private const string SourceRoot = "Assets/ThirdParty/MicrosoftRocketbox/Avatars";
        private const string AnimationRoot = "Assets/Resources/PassengerBases/RocketboxAnimations";
        private const string GeneratedRoot = "Assets/Resources/PassengerBases/Generated";
        internal const string MaterialFolder = GeneratedRoot + "/Materials";
        private const string MeshFolder = GeneratedRoot + "/Meshes";
        private const string PrefabFolder = GeneratedRoot + "/Prefabs";
        private const string ControllerPath = GeneratedRoot + "/RocketboxPassenger.controller";

        [MenuItem("Metro Replay/Build Rocketbox Passenger Library")]
        public static void EnsureBuilt()
        {
            EnsureFolders();
            AssetDatabase.Refresh();
            var modelPaths = DiscoverModelPaths();
            var controller = BuildController();
            foreach (var modelPath in modelPaths)
                BuildPrefab(modelPath, controller);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log($"ROCKETBOX_LIBRARY_BUILT=BASES={modelPaths.Length};LOD_LEVELS=3");
        }

        private static string[] DiscoverModelPaths()
        {
            var paths = AssetDatabase.FindAssets("t:Model", new[] { SourceRoot })
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(IsBaseCharacterModel)
                .OrderBy(path => path, StringComparer.Ordinal)
                .ToArray();
            if (paths.Length == 0)
                throw new FileNotFoundException("No Rocketbox base character models were found.", SourceRoot);

            var duplicateNames = paths
                .GroupBy(Path.GetFileNameWithoutExtension, StringComparer.Ordinal)
                .Where(group => group.Count() > 1)
                .Select(group => group.Key)
                .ToArray();
            if (duplicateNames.Length > 0)
                throw new InvalidOperationException(
                    "Rocketbox base character names must be unique: " + string.Join(", ", duplicateNames));
            return paths;
        }

        private static bool IsBaseCharacterModel(string path)
        {
            if (!path.EndsWith(".fbx", StringComparison.OrdinalIgnoreCase) ||
                path.IndexOf("/Export/", StringComparison.Ordinal) < 0)
                return false;
            var fileName = Path.GetFileNameWithoutExtension(path);
            var exportFolder = Path.GetDirectoryName(path);
            var characterFolder = exportFolder == null
                ? null
                : Path.GetFileName(Path.GetDirectoryName(exportFolder));
            return string.Equals(fileName, characterFolder, StringComparison.Ordinal);
        }

        private static void BuildPrefab(string modelPath, RuntimeAnimatorController controller)
        {
            var baseName = Path.GetFileNameWithoutExtension(modelPath);
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
            var path = $"{AnimationRoot}/{fileName}";
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
