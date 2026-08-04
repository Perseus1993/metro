using System;
using System.IO;
using MetroReplay.Presentation;
using UnityEditor;
using UnityEngine;

namespace MetroReplay.Editor
{
    [InitializeOnLoad]
    public static class StationFireVisualCapture
    {
        private const string PendingKey = "MetroReplay.StationFireCapture.Pending";
        private const string CapturedKey = "MetroReplay.StationFireCapture.Captured";
        private const string OutputKey = "MetroReplay.StationFireCapture.Output";
        private static double _readyAt;
        private static double _stopAt;

        static StationFireVisualCapture()
        {
            EditorApplication.playModeStateChanged -= OnPlayModeChanged;
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.update -= Tick;
            EditorApplication.update += Tick;
        }

        [MenuItem("Hazard Visual Lab/Capture Station Fire Visual")]
        public static void Capture()
        {
            var outputArgument = GetArgument("--capture-output");
            var output = string.IsNullOrWhiteSpace(outputArgument)
                ? Path.GetFullPath("Assets/Screenshots/station_fire_operations_validation.png")
                : Path.GetFullPath(outputArgument);
            Directory.CreateDirectory(Path.GetDirectoryName(output) ?? "Assets/Screenshots");
            SessionState.SetString(OutputKey, output);
            SessionState.SetBool(CapturedKey, false);
            SessionState.SetBool(PendingKey, true);
            EditorApplication.EnterPlaymode();
        }

        private static void OnPlayModeChanged(PlayModeStateChange state)
        {
            if (!SessionState.GetBool(PendingKey, false))
                return;
            if (state == PlayModeStateChange.EnteredPlayMode)
            {
                _readyAt = EditorApplication.timeSinceStartup + 4.0;
                _stopAt = 0.0;
            }
            else if (state == PlayModeStateChange.EnteredEditMode
                     && SessionState.GetBool(CapturedKey, false))
            {
                SessionState.EraseBool(PendingKey);
                SessionState.EraseBool(CapturedKey);
                Debug.Log("STATION_FIRE_VISUAL_CAPTURE_COMPLETE=" + SessionState.GetString(OutputKey, string.Empty));
                if (UnityEngine.Application.isBatchMode)
                    EditorApplication.Exit(0);
            }
        }

        private static void Tick()
        {
            if (!SessionState.GetBool(PendingKey, false) || !EditorApplication.isPlaying)
                return;
            var now = EditorApplication.timeSinceStartup;
            if (!SessionState.GetBool(CapturedKey, false))
            {
                if (now < _readyAt)
                    return;
                var visualCount = UnityEngine.Object.FindObjectsByType<VisualOnlyStationAssetIdentity>(
                    FindObjectsInactive.Exclude,
                    FindObjectsSortMode.None).Length;
                if (visualCount < 6)
                {
                    _readyAt = now + 0.25;
                    return;
                }
                var output = SessionState.GetString(OutputKey, string.Empty);
                ConfigureRequestedView();
                LogVisualPositions();
                CaptureCamera(output);
                SessionState.SetBool(CapturedKey, true);
                _stopAt = now + 1.5;
                Debug.Log($"STATION_FIRE_VISUAL_CAPTURE_REQUESTED={output};VISUALS={visualCount}");
                return;
            }
            if (_stopAt > 0.0 && now >= _stopAt)
                EditorApplication.ExitPlaymode();
        }

        private static void LogVisualPositions()
        {
            var camera = Camera.main ?? UnityEngine.Object.FindFirstObjectByType<Camera>();
            if (camera == null)
                return;
            foreach (var identity in UnityEngine.Object.FindObjectsByType<VisualOnlyStationAssetIdentity>(
                         FindObjectsInactive.Exclude,
                         FindObjectsSortMode.None))
            {
                var renderers = identity.GetComponentsInChildren<Renderer>(true);
                var center = identity.transform.position;
                if (renderers.Length > 0)
                {
                    var bounds = renderers[0].bounds;
                    for (var index = 1; index < renderers.Length; index++)
                        bounds.Encapsulate(renderers[index].bounds);
                    center = bounds.center;
                }
                Debug.Log(
                    $"STATION_VISUAL_SCREEN={identity.AssetId};WORLD={center:F2};" +
                    $"SCREEN={camera.WorldToScreenPoint(center):F1}");
            }
        }

        private static void CaptureCamera(string output)
        {
            var camera = Camera.main ?? UnityEngine.Object.FindFirstObjectByType<Camera>();
            if (camera == null)
                throw new InvalidOperationException("No station camera is available for validation capture.");
            const int width = 1600;
            const int height = 900;
            var previousTarget = camera.targetTexture;
            var previousActive = RenderTexture.active;
            var previousAspect = camera.aspect;
            var target = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            var texture = new Texture2D(width, height, TextureFormat.RGB24, false);
            try
            {
                camera.aspect = width / (float)height;
                camera.targetTexture = target;
                camera.Render();
                RenderTexture.active = target;
                texture.ReadPixels(new Rect(0f, 0f, width, height), 0, 0, false);
                texture.Apply(false, false);
                File.WriteAllBytes(output, texture.EncodeToPNG());
            }
            finally
            {
                camera.targetTexture = previousTarget;
                camera.aspect = previousAspect;
                RenderTexture.active = previousActive;
                UnityEngine.Object.DestroyImmediate(texture);
                UnityEngine.Object.DestroyImmediate(target);
            }
        }

        private static void ConfigureRequestedView()
        {
            var view = GetArgument("--capture-view");
            if (string.IsNullOrWhiteSpace(view))
                return;
            var application = UnityEngine.Object.FindFirstObjectByType<ReplayApplicationRoot>();
            var camera = UnityEngine.Object.FindFirstObjectByType<OrbitCameraController>();
            if (application?.Data == null || camera == null)
                return;

            if (string.Equals(view, "security", StringComparison.OrdinalIgnoreCase))
            {
                camera.SetView(
                    application.Data.ToWorld(47.8f, 11.8f, "b1_concourse", 1.15f),
                    14.5f,
                    165f,
                    7f);
                return;
            }
            if (string.Equals(view, "equipment", StringComparison.OrdinalIgnoreCase))
            {
                var identities = UnityEngine.Object.FindObjectsByType<VisualOnlyStationAssetIdentity>(
                    FindObjectsInactive.Exclude,
                    FindObjectsSortMode.None);
                var target = Vector3.zero;
                var count = 0;
                foreach (var identity in identities)
                {
                    if (identity.AssetId != "Manual fire alarm call point"
                        && identity.AssetId != "Electrical distribution cabinet"
                        && identity.AssetId != "Station wall clock")
                        continue;
                    target += identity.transform.position;
                    count++;
                }
                if (count > 0)
                    target /= count;
                camera.SetView(
                    target,
                    4.8f,
                    180f,
                    5f);
                return;
            }
            if (string.Equals(view, "cleaning", StringComparison.OrdinalIgnoreCase))
            {
                camera.SetView(
                    application.Data.ToWorld(58.7f, 9.25f, "b1_concourse", 0.85f),
                    6.2f,
                    205f,
                    8f);
            }
        }

        private static string GetArgument(string name)
        {
            var arguments = Environment.GetCommandLineArgs();
            for (var index = 0; index < arguments.Length - 1; index++)
            {
                if (string.Equals(arguments[index], name, StringComparison.OrdinalIgnoreCase))
                    return arguments[index + 1];
            }
            return null;
        }
    }
}
