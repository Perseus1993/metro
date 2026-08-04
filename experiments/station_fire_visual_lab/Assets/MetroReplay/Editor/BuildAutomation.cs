using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Editor
{
    public static class BuildAutomation
    {
        private const string ScenePath = "Assets/Scenes/MetroReplay.unity";
        private const string DefaultReplayPath = "Assets/StreamingAssets/replay.json";

        [MenuItem("Metro Replay/Prepare Project")]
        public static void PrepareProject()
        {
            if (!File.Exists(DefaultReplayPath))
                throw new FileNotFoundException(
                    "The double-click Windows clearance demo requires a packaged clearance replay.",
                    DefaultReplayPath);
            HdrpProjectConfigurator.EnsureConfigured();
            StationSafetyAssetBuilder.EnsureBuilt();
            RocketboxPassengerPrefabBuilder.EnsureBuilt();
            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath) ?? "Assets/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            EditorSceneManager.SaveScene(scene, ScenePath);

            EditorBuildSettings.scenes = new[]
            {
                new EditorBuildSettingsScene(ScenePath, true)
            };
            PlayerSettings.companyName = "Metro Simulation Lab";
            PlayerSettings.productName = "Metro Station 3D Replay";
            // Mono is part of the base Unity editor installation and keeps the
            // first deliverable reproducible without an additional 2–4 GB module.
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
            PlayerSettings.defaultScreenWidth = 1600;
            PlayerSettings.defaultScreenHeight = 900;
            PlayerSettings.runInBackground = true;
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.SetGraphicsAPIs(BuildTarget.StandaloneWindows64, new[]
            {
                GraphicsDeviceType.Direct3D12,
                GraphicsDeviceType.Direct3D11
            });
            AssetDatabase.SaveAssets();
            Debug.Log("METRO_REPLAY_PREPARED=" + ScenePath);
        }

        [MenuItem("Metro Replay/Build Windows")]
        public static void BuildWindows()
        {
            PrepareProject();
            var output = GetArgument("--build-output")
                ?? Path.GetFullPath(Path.Combine(UnityEngine.Application.dataPath, "..", "Builds", "Windows", "MetroStation3DReplay.exe"));
            Directory.CreateDirectory(Path.GetDirectoryName(output) ?? "Builds");
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = output,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.CleanBuildCache
            };
            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
                throw new InvalidOperationException($"Windows build failed: {report.summary.result}, {report.summary.totalErrors} errors.");
            Debug.Log($"METRO_REPLAY_BUILD={output};SIZE={report.summary.totalSize}");
        }

        private static string GetArgument(string name)
        {
            var arguments = Environment.GetCommandLineArgs();
            for (var i = 0; i < arguments.Length - 1; i++)
            {
                if (string.Equals(arguments[i], name, StringComparison.OrdinalIgnoreCase))
                    return Path.GetFullPath(arguments[i + 1]);
            }
            return null;
        }
    }
}
