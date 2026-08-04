using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using MetroReplay.Application;
using MetroReplay.Domain;
using MetroReplay.Infrastructure;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class ReplayApplicationRoot : MonoBehaviour
    {
        private const float DefaultClearanceStartTime = 0f;
        private readonly List<PassengerPose> _poses = new List<PassengerPose>(512);
        private ReplayData _data;
        private ReplayClock _clock;
        private ReplaySampler _sampler;
        private PassengerPool _passengers;
        private PassengerAvatarLoader _avatarLoader;
        private PassengerSkinAtlas _skinAtlas;
        private IDisposable _passengerShowcase;
        private StationDecorationLayer _decorationLayer;
        private PlatformPresentationLayer _platformPresentationLayer;
        private MetroTrainReplayPresenter _trainPresenter;
        private ElevatorReplayPresenter _elevatorPresenter;
        private ClearanceCameraDirector _clearanceCameraDirector;
        private OpeningCameraStoryDirector _openingCameraStoryDirector;
        private Transform _stationRoot;
        private Transform _passengerRoot;
        private AcceptanceRecorder _acceptance;
        private string _error;
        private string _avatarStatus = "3D 人物载入中";
        private string _skinStatus = "皮肤载入中";
        private string _decorationStatus = "CC0 装饰载入中";
        private bool _visualAssetsReady;
        private bool _skinShowcaseRequested;
        private bool _heroSceneRequested;
        private bool _platformHeroRequested;
        private bool _clearanceHeroRequested;
        private bool _cleanScreenshotRequested;
        private bool _promotionalVideoCaptureRequested;
        private string _sourcePath;
        private GUIStyle _panelStyle;
        private GUIStyle _titleStyle;
        private GUIStyle _progressStyle;

        public ReplayClock Clock => _clock;
        public ReplayData Data => _data;
        public string SourcePath => _sourcePath;

        private void Awake()
        {
            UnityEngine.Application.targetFrameRate = 60;
            QualitySettings.vSyncCount = 0;
            _promotionalVideoCaptureRequested = PromotionalVideoCapture.IsActive;
            TryLoad();
        }

        private void Update()
        {
            if (_clock == null || _sampler == null || _passengers == null)
                return;
            if (Input.GetKeyDown(KeyCode.Space))
                _clock.Toggle();
            if (Input.GetKeyDown(KeyCode.LeftArrow))
                _clock.Seek(_clock.Time - 5f);
            if (Input.GetKeyDown(KeyCode.RightArrow))
                _clock.Seek(_clock.Time + 5f);

            _openingCameraStoryDirector?.Tick(UnityEngine.Time.unscaledDeltaTime);
            _clock.Tick(UnityEngine.Time.unscaledDeltaTime);
            RenderCurrentTime();
            if (_visualAssetsReady && _acceptance != null
                && _acceptance.Tick(UnityEngine.Time.unscaledDeltaTime, _passengers.ActiveCount))
                UnityEngine.Application.Quit(0);
        }

        private void TryLoad()
        {
            try
            {
                _sourcePath = ResolveReplayPath(Environment.GetCommandLineArgs());
                if (!File.Exists(_sourcePath))
                    throw new FileNotFoundException("Replay JSON was not found.", _sourcePath);
                _data = ReplayContractReader.Read(File.ReadAllText(_sourcePath));
                _clock = new ReplayClock(_data.Duration);
                _sampler = new ReplaySampler(_data);

                var arguments = Environment.GetCommandLineArgs();
                _heroSceneRequested = HasArgument(arguments, "--b1-hero");
                _platformHeroRequested = ShouldUsePlatformHero(arguments);
                _clearanceHeroRequested = ShouldUseClearanceHero(arguments);
                _cleanScreenshotRequested = HasArgument(arguments, "--clean-screenshot");

                _stationRoot = new GameObject("StationScene").transform;
                _stationRoot.SetParent(transform, false);
                var bounds = new StationSceneBuilder(_stationRoot).Build(_data);
                _elevatorPresenter = new ElevatorReplayPresenter(_stationRoot, _data);
                _platformPresentationLayer = new PlatformPresentationLayer();
                B1HeroView? platformHeroView = null;
                if (_platformPresentationLayer.Build(_stationRoot, _data, out var resolvedPlatformView))
                    platformHeroView = resolvedPlatformView;
                if (ShouldShowTrain(arguments))
                    _trainPresenter = new MetroTrainReplayPresenter(
                        _stationRoot,
                        _data,
                        _clearanceHeroRequested);
                B1HeroView? b1HeroView = null;
                if (_heroSceneRequested || _clearanceHeroRequested)
                    b1HeroView = new B1HeroSceneBuilder(
                        _stationRoot,
                        _data,
                        _clearanceHeroRequested).Build();
                B1HeroView? heroView = null;
                if (_heroSceneRequested)
                    heroView = b1HeroView;
                else if (_platformHeroRequested)
                    heroView = platformHeroView;
                else if (_clearanceHeroRequested
                    && ClearanceHeroViewResolver.TryResolve(_data, _sampler, out var clearanceView))
                    heroView = clearanceView;
                _passengerRoot = new GameObject("PassengerPool").transform;
                _passengerRoot.SetParent(transform, false);
                _passengers = new PassengerPool(_passengerRoot, 320);

                _skinShowcaseRequested = HasArgument(arguments, "--skin-showcase");
                var cameraController = BuildLightingAndCamera(
                    ResolveCameraBounds(_data, arguments, bounds),
                    heroView,
                    !b1HeroView.HasValue);
                if (_clearanceHeroRequested)
                    _clearanceCameraDirector = new ClearanceCameraDirector(
                        _data,
                        cameraController,
                        b1HeroView);
                if (b1HeroView.HasValue && ShouldUseOpeningStory(arguments))
                    _openingCameraStoryDirector = OpeningCameraStoryDirector.TryCreate(
                        _stationRoot,
                        cameraController,
                        b1HeroView.Value,
                        platformHeroView ?? b1HeroView.Value,
                        bounds);
                var acceptancePath = GetArgument(arguments, "--acceptance-out");
                var acceptanceSeconds = ParseFloat(GetArgument(arguments, "--acceptance-seconds"), 120f);
                _acceptance = new AcceptanceRecorder(_data, acceptancePath, acceptanceSeconds);
                LoadVisualAssetsAsync();
                _clock.Seek(ResolveInitialTime(arguments));
                _clock.Play();
                RenderCurrentTime();
                var screenshotPath = GetArgument(arguments, "--screenshot-out");
                if (!string.IsNullOrWhiteSpace(screenshotPath))
                    StartCoroutine(CaptureScreenshot(Path.GetFullPath(screenshotPath)));
            }
            catch (Exception exception)
            {
                _error = exception.ToString();
                Debug.LogException(exception);
            }
        }

        private async void LoadVisualAssetsAsync()
        {
            GameObject avatarPrototype = null;
            var rocketboxLoaded = false;
            try
            {
                var library = RocketboxPassengerLibrary.Load();
                if (library.BaseCount < 6 || library.LodLevelCount < 3)
                    throw new InvalidOperationException("Rocketbox generated passenger library is incomplete.");
                _passengers.UsePrototypes(library.Prototypes);
                _avatarStatus =
                    $"Rocketbox 乘客 {library.BaseCount} 套 · 运营人员 {library.OperationsBaseCount + library.SecurityBaseCount} 套 · 三级 LOD";
                _skinStatus = $"服装 {PassengerAppearancePalette.ClothingVariantCount} 色 · 肤色 {PassengerAppearancePalette.SkinVariantCount} 档";
                _acceptance?.SetPassengerRepresentation("rocketbox_humanoid_lod3");
                _acceptance?.SetPassengerAssetEvidence(
                    library.BaseCount,
                    library.BaseCount * PassengerAppearancePalette.ClothingVariantCount
                        * PassengerAppearancePalette.SkinVariantCount,
                    library.LodLevelCount);
                if (_skinShowcaseRequested)
                {
                    EnterShowcaseMode();
                    var showcase = new PassengerBaseShowcase();
                    showcase.Build(library.Prototypes, _stationRoot, Camera.main);
                    _passengerShowcase = showcase;
                }
                rocketboxLoaded = true;
                RenderCurrentTime();
            }
            catch (Exception exception)
            {
                Debug.LogWarning("Rocketbox passenger library was unavailable; using legacy fallback. " + exception.Message);
            }

            if (!rocketboxLoaded)
            {
                try
                {
                    _avatarLoader = new PassengerAvatarLoader();
                    var assetPath = Path.Combine(
                        UnityEngine.Application.streamingAssetsPath,
                        "AnimationLibrary_Godot_Standard.glb");
                    avatarPrototype = await _avatarLoader.LoadPrototypeAsync(assetPath);
                    _passengers.UsePrototype(avatarPrototype);
                    _avatarStatus = "Quaternius 3D 骨骼人物（后备）";
                    _acceptance?.SetPassengerRepresentation("quaternius_glb_skinned");
                    RenderCurrentTime();
                }
                catch (Exception exception)
                {
                    _avatarStatus = "胶囊后备（3D 人物载入失败）";
                    _acceptance?.SetPassengerRepresentation("capsule_fallback");
                    Debug.LogException(exception);
                }
            }

            if (!rocketboxLoaded && _passengers.UsesThreeDimensionalAvatar)
            {
                try
                {
                    var skinPath = Path.Combine(
                        UnityEngine.Application.streamingAssetsPath,
                        "PassengerSkins",
                        "commuter_skin_atlas_v1.png");
                    _skinAtlas = PassengerSkinAtlas.Load(skinPath);
                    _passengers.UseSkinAtlas(_skinAtlas);
                    _skinStatus = $"共享皮肤 {PassengerSkinAtlas.VariantCount} 套";
                    _acceptance?.SetPassengerSkinEvidence(
                        PassengerSkinAtlas.VariantCount,
                        "generated_commuter_atlas_v1");
                    if (_skinShowcaseRequested)
                    {
                        EnterShowcaseMode();
                        var showcase = new PassengerSkinShowcase();
                        showcase.Build(avatarPrototype, _skinAtlas, _stationRoot, Camera.main);
                        _passengerShowcase = showcase;
                    }
                    RenderCurrentTime();
                }
                catch (Exception exception)
                {
                    _skinStatus = "原始纯色材质（皮肤载入失败）";
                    _acceptance?.SetPassengerSkinEvidence(0, "unavailable");
                    Debug.LogException(exception);
                }
            }
            else if (!rocketboxLoaded)
            {
                _skinStatus = "无皮肤图集";
                _acceptance?.SetPassengerSkinEvidence(0, "unavailable");
            }

            if (rocketboxLoaded)
                _acceptance?.SetPassengerSkinEvidence(0, "rocketbox_material_variants");

            try
            {
                _decorationLayer = new StationDecorationLayer();
                await _decorationLayer.BuildAsync(
                    _stationRoot,
                    _data,
                    UnityEngine.Application.streamingAssetsPath);
                _decorationStatus = $"CC0 装饰 {_decorationLayer.InstanceCount} 件";
                _acceptance?.SetDecorationEvidence(_decorationLayer.InstanceCount, "kenney_polyhaven_cc0");
            }
            catch (Exception exception)
            {
                _decorationStatus = "程序几何后备（装饰载入失败）";
                _acceptance?.SetDecorationEvidence(0, "procedural_fallback");
                Debug.LogException(exception);
            }
            _visualAssetsReady = true;
        }

        private void EnterShowcaseMode()
        {
            if (_stationRoot != null)
                _stationRoot.gameObject.SetActive(false);
            if (_passengerRoot != null)
                _passengerRoot.gameObject.SetActive(false);
        }

        private void OnDestroy()
        {
            _avatarLoader?.Dispose();
            _passengerShowcase?.Dispose();
            _skinAtlas?.Dispose();
            _decorationLayer?.Dispose();
            _platformPresentationLayer?.Dispose();
            _trainPresenter?.Dispose();
        }

        private void RenderCurrentTime()
        {
            _sampler.Sample(_clock.Time, _poses);
            _elevatorPresenter?.Sync(_clock.Time);
            _passengers.Sync(_poses);
            if (_openingCameraStoryDirector == null)
                _clearanceCameraDirector?.Sync(_poses);
            _trainPresenter?.Sync(_clock.Time);
        }

        private static OrbitCameraController BuildLightingAndCamera(
            Bounds bounds,
            B1HeroView? heroView,
            bool addDefaultLighting)
        {
            if (addDefaultLighting)
            {
                RenderSettings.ambientLight = new Color(0.46f, 0.49f, 0.55f);
                var lightObject = new GameObject("KeyLight");
                var light = lightObject.AddComponent<Light>();
                light.type = LightType.Directional;
                light.intensity = 850f;
                light.shadows = LightShadows.Soft;
                lightObject.transform.rotation = Quaternion.Euler(48f, -32f, 0f);
                HdrpStationLook.EnsureAdditionalLightData(light);
                HdrpStationLook.KeepOnlyGeneratedDirectionalLight(light);
            }

            HdrpStationLook.Build(GameObject.Find("StationScene").transform, bounds);

            var cameraObject = new GameObject("ReplayCamera");
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.035f, 0.047f, 0.067f);
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 500f;
            cameraObject.tag = "MainCamera";
            HdrpStationLook.ConfigureCamera(camera);
            var controller = cameraObject.AddComponent<OrbitCameraController>();
            if (heroView.HasValue)
            {
                var view = heroView.Value;
                controller.SetView(view.Target, view.Distance, view.Yaw, view.Pitch);
            }
            else
            {
                controller.Frame(bounds);
            }
            return controller;
        }

        private static Bounds ResolveCameraBounds(
            ReplayData data,
            IReadOnlyList<string> arguments,
            Bounds fallback)
        {
            var entityId = GetArgument(arguments, "--camera-entity");
            if (string.IsNullOrWhiteSpace(entityId))
                return fallback;
            foreach (var entity in data.Entities)
            {
                if (!string.Equals(entity.Id, entityId, StringComparison.Ordinal))
                    continue;
                var levelId = entity.LevelIds[0];
                var center = data.ToWorld(entity.Geometry.Center.x, entity.Geometry.Center.y, levelId, 1.1f);
                var size = new Vector3(8f, 4f, 8f);
                if (entity.Geometry.Points.Count > 0)
                {
                    var min = new Vector3(float.PositiveInfinity, center.y, float.PositiveInfinity);
                    var max = new Vector3(float.NegativeInfinity, center.y, float.NegativeInfinity);
                    foreach (var point in entity.Geometry.Points)
                    {
                        var world = data.ToWorld(point.x, point.y, levelId, 1.1f);
                        min = Vector3.Min(min, world);
                        max = Vector3.Max(max, world);
                    }
                    center = (min + max) * 0.5f;
                    size = new Vector3(Mathf.Max(8f, max.x - min.x), 4f, Mathf.Max(8f, max.z - min.z));
                }
                return new Bounds(center, size);
            }
            return fallback;
        }

        private void OnGUI()
        {
            if (_cleanScreenshotRequested || _promotionalVideoCaptureRequested)
                return;
            EnsureStyles();
            if (!string.IsNullOrEmpty(_error))
            {
                GUI.Box(new Rect(20f, 20f, Mathf.Min(Screen.width - 40f, 900f), 240f), "Unity 回放载入失败\n\n" + _error, _panelStyle);
                return;
            }
            if (_clock == null)
                return;
            if (_openingCameraStoryDirector != null && _openingCameraStoryDirector.IsActive)
                return;

            const float width = 900f;
            var panel = new Rect(18f, Screen.height - 144f, Mathf.Min(width, Screen.width - 36f), 126f);
            var totalPassengers = _data.ClearanceAudit.TotalPassengers > 0
                ? _data.ClearanceAudit.TotalPassengers
                : Mathf.Max(_passengers.ActiveCount, 1);
            var remainingPassengers = Mathf.Clamp(_passengers.ActiveCount, 0, totalPassengers);
            var departedPassengers = totalPassengers - remainingPassengers;
            var clearanceProgress = totalPassengers == 0
                ? 0f
                : (float)departedPassengers / totalPassengers;
            var clearanceStatus = remainingPassengers == 0 ? "清场完成" : "清场进行中";
            GUI.Box(panel, GUIContent.none, _panelStyle);
            GUI.Label(new Rect(panel.x + 14f, panel.y + 9f, panel.width - 28f, 24f),
                $"{totalPassengers} 人清场  |  已离场 {departedPassengers}  |  剩余 {remainingPassengers}  |  {clearanceStatus}  |  {_clock.Time:0.0}s / {_clock.Duration:0.0}s",
                _titleStyle);

            var progressRect = new Rect(panel.x + 14f, panel.y + 36f, panel.width - 28f, 18f);
            var previousColor = GUI.color;
            GUI.color = new Color(0.08f, 0.12f, 0.17f, 0.95f);
            GUI.DrawTexture(progressRect, Texture2D.whiteTexture);
            GUI.color = remainingPassengers == 0
                ? new Color(0.16f, 0.76f, 0.44f, 0.96f)
                : new Color(0.10f, 0.48f, 0.90f, 0.96f);
            GUI.DrawTexture(
                new Rect(progressRect.x, progressRect.y, progressRect.width * clearanceProgress, progressRect.height),
                Texture2D.whiteTexture);
            GUI.color = previousColor;
            GUI.Label(progressRect, $"已离场 {departedPassengers} / {totalPassengers}", _progressStyle);

            if (GUI.Button(new Rect(panel.x + 14f, panel.y + 62f, 70f, 25f), _clock.IsPlaying ? "暂停" : "播放"))
                _clock.Toggle();
            var speeds = new[] { 0.5f, 1f, 2f, 4f, 8f };
            for (var i = 0; i < speeds.Length; i++)
            {
                if (GUI.Button(new Rect(panel.x + 92f + i * 49f, panel.y + 62f, 44f, 25f), speeds[i] + "x"))
                    _clock.SetSpeed(speeds[i]);
            }

            var sliderRect = new Rect(panel.x + 14f, panel.y + 100f, panel.width - 28f, 20f);
            var nextTime = GUI.HorizontalSlider(sliderRect, _clock.Time, 0f, Mathf.Max(0.001f, _clock.Duration));
            if (Mathf.Abs(nextTime - _clock.Time) > 0.001f)
            {
                _clock.Seek(nextTime);
                RenderCurrentTime();
            }

            GUI.Label(new Rect(18f, 18f, Mathf.Min(Screen.width - 36f, 900f), 23f),
                _skinShowcaseRequested
                    ? "八套写实通勤者预览 · 服装/肤色变化 · High/Mid/Low 三级 LOD"
                    : ReplayHeader(totalPassengers),
                _titleStyle);

            var legend = new Rect(Screen.width - 232f, 18f, 214f, 178f);
            GUI.Box(legend, GUIContent.none, _panelStyle);
            GUI.Label(new Rect(legend.x + 12f, legend.y + 8f, 190f, 22f), "场景图例", _titleStyle);
            DrawLegendItem(legend.x + 12f, legend.y + 36f, new Color(0.20f, 0.72f, 0.48f), "入口");
            DrawLegendItem(legend.x + 12f, legend.y + 58f, new Color(0.16f, 0.53f, 0.90f), "闸机");
            DrawLegendItem(legend.x + 12f, legend.y + 80f, new Color(0.95f, 0.61f, 0.17f), "扶梯");
            DrawLegendItem(legend.x + 12f, legend.y + 102f, new Color(0.22f, 0.78f, 0.87f), "电梯");
            DrawLegendItem(legend.x + 12f, legend.y + 124f, new Color(0.62f, 0.50f, 0.87f), "楼梯");
            GUI.Label(new Rect(legend.x + 12f, legend.y + 148f, 190f, 20f), "B1 -6m  ·  B2 -14m");
        }

        private void EnsureStyles()
        {
            if (_panelStyle != null)
                return;
            _panelStyle = new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                padding = new RectOffset(14, 14, 12, 12),
                fontSize = 13,
                wordWrap = true
            };
            _titleStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 14,
                fontStyle = FontStyle.Bold,
                normal = { textColor = Color.white }
            };
            _progressStyle = new GUIStyle(GUI.skin.label)
            {
                alignment = TextAnchor.MiddleCenter,
                fontSize = 12,
                fontStyle = FontStyle.Bold,
                normal = { textColor = Color.white }
            };
        }

        private IEnumerator CaptureScreenshot(string outputPath)
        {
            var directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(directory))
                Directory.CreateDirectory(directory);
            while (!_visualAssetsReady)
                yield return null;
            yield return new WaitForSecondsRealtime(2f);
            ScreenCapture.CaptureScreenshot(outputPath, 1);
            yield return new WaitForSecondsRealtime(1f);
            UnityEngine.Application.Quit(0);
        }

        private static void DrawLegendItem(float x, float y, Color color, string label)
        {
            var previous = GUI.color;
            GUI.color = color;
            GUI.DrawTexture(new Rect(x, y + 2f, 14f, 14f), Texture2D.whiteTexture);
            GUI.color = previous;
            GUI.Label(new Rect(x + 22f, y, 150f, 20f), label);
        }

        private string ReplayHeader(int totalPassengers)
        {
            if (_data.Fidelity.IsAuthoritative)
            {
                var routing = _data.Fidelity.RoutingPluginIds.Count > 0
                    ? _data.Fidelity.RoutingPluginIds[0]
                    : "internal_graph";
                return $"{totalPassengers} 人高保真清场 · 权威快照 {_data.Fidelity.SnapshotIntervalSeconds:0.#}s · {routing} · 右键旋转 · 滚轮缩放 · 空格暂停";
            }
            return $"{totalPassengers} 人完整清场 · 列车与全部垂直交通设施默认可见 · 右键旋转 · 滚轮缩放 · 空格暂停";
        }

        public static string ResolveReplayPath(string[] arguments)
        {
            var explicitPath = GetArgument(arguments, "--replay-json");
            if (!string.IsNullOrWhiteSpace(explicitPath))
                return Path.GetFullPath(explicitPath);
            var environmentPath = Environment.GetEnvironmentVariable("METRO_REPLAY_JSON");
            if (!string.IsNullOrWhiteSpace(environmentPath))
                return Path.GetFullPath(environmentPath);

            var streaming = Path.Combine(UnityEngine.Application.streamingAssetsPath, "replay.json");
            if (File.Exists(streaming))
                return streaming;

            var directory = new DirectoryInfo(UnityEngine.Application.dataPath);
            while (directory != null)
            {
                var replayDirectory = Path.Combine(directory.FullName, "output", "unity_replay");
                if (Directory.Exists(replayDirectory))
                    return Path.Combine(replayDirectory, "clearance_50_complete.replay.json");
                directory = directory.Parent;
            }

            return Path.GetFullPath(Path.Combine(
                UnityEngine.Application.dataPath,
                "..",
                "output",
                "unity_replay",
                "clearance_50_complete.replay.json"));
        }

        private static float ResolveInitialTime(IReadOnlyList<string> arguments)
        {
            return ParseFloat(GetArgument(arguments, "--start-time"), DefaultClearanceStartTime);
        }

        private static bool ShouldUsePlatformHero(IReadOnlyList<string> arguments)
        {
            return HasArgument(arguments, "--platform-hero");
        }

        private static bool ShouldUseClearanceHero(IReadOnlyList<string> arguments)
        {
            return !HasArgument(arguments, "--b1-hero")
                && !HasArgument(arguments, "--platform-hero")
                && !HasArgument(arguments, "--skin-showcase")
                && string.IsNullOrWhiteSpace(GetArgument(arguments, "--camera-entity"));
        }

        private static bool ShouldShowTrain(IReadOnlyList<string> arguments)
        {
            return !HasArgument(arguments, "--hide-train");
        }

        private static bool ShouldUseOpeningStory(IReadOnlyList<string> arguments)
        {
            return !StationFireVisualDemo.Enabled
                && !HasArgument(arguments, "--skip-opening-story")
                && !HasArgument(arguments, "--acceptance-out")
                && !HasArgument(arguments, "--screenshot-out")
                && !HasArgument(arguments, "--clean-screenshot")
                && !HasArgument(arguments, "-runTests");
        }

        private static string GetArgument(IReadOnlyList<string> arguments, string name)
        {
            for (var i = 0; i < arguments.Count - 1; i++)
            {
                if (string.Equals(arguments[i], name, StringComparison.OrdinalIgnoreCase))
                    return arguments[i + 1];
            }
            return null;
        }

        private static bool HasArgument(IReadOnlyList<string> arguments, string name)
        {
            for (var i = 0; i < arguments.Count; i++)
            {
                if (string.Equals(arguments[i], name, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        private static float ParseFloat(string value, float fallback)
        {
            return float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var result)
                ? result
                : fallback;
        }
    }
}
