using System;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace MetroReplay.Presentation
{
    public static class BrandIntroBootstrap
    {
        public const string PreviewHoldPrefKey = "MetroReplay.BrandIntro.PreviewHold";
        public const string PreviewLoopPrefKey = "MetroReplay.BrandIntro.PreviewLoop";
        public const float IntroBloomIntensity = 0.025f;
        public const float IntroBloomThreshold = 1.6f;
        public const float IntroBloomScatter = 0.28f;

        internal static bool EnsureIntroExists()
        {
            if (StationFireVisualDemo.Enabled)
                return false;

            Debug.Log($"[BrandIntro] Ensure requested. batch={UnityEngine.Application.isBatchMode}; args={string.Join(" ", Environment.GetCommandLineArgs())}");
            if (UnityEngine.Application.isBatchMode || ShouldSkip(Environment.GetCommandLineArgs()))
                return false;

            var existingIntros = UnityEngine.Object.FindObjectsByType<BrandIntroController>(
                FindObjectsInactive.Include,
                FindObjectsSortMode.None);
            foreach (var existingIntro in existingIntros)
            {
                if (existingIntro == null)
                    continue;
                existingIntro.gameObject.SetActive(true);
                return true;
            }

            // Some Player startup paths do not preserve objects created before
            // the first scene transition. Recreate the splash from the confirmed
            // AfterSceneLoad bootstrap before the simulation root is constructed.
            CreateIntroObject();
            return true;
        }

        private static void CreateIntroObject()
        {
            Debug.Log("[BrandIntro] Creating runtime intro root.");
            var intro = new GameObject("GenWorld · Perseus Brand Intro")
            {
                // Runtime-only splash layer: never serialize it into an authored scene.
                hideFlags = HideFlags.DontSave
            };
            UnityEngine.Object.DontDestroyOnLoad(intro);
            intro.AddComponent<BrandIntroController>();
        }

        private static bool ShouldSkip(IReadOnlyList<string> arguments)
        {
            var skipArguments = new[]
            {
                "--skip-brand-intro",
                "--acceptance-out",
                "--screenshot-out",
                "--clean-screenshot",
                "-runTests"
            };
            foreach (var argument in arguments)
            {
                foreach (var skipArgument in skipArguments)
                {
                    if (string.Equals(argument, skipArgument, StringComparison.OrdinalIgnoreCase))
                        return true;
                }
            }
            return false;
        }
    }

    [DefaultExecutionOrder(10000)]
    internal sealed class BrandIntroController : MonoBehaviour
    {
        private const int IntroLayer = 31;
        private const int VisibleWarmupFrames = 18;
        private const float FadeFromBlackEnd = 0.65f;
        private const float SkipInputUnlockTime = 3.45f;
        private const float SpinStart = 0.30f;
        private const float SpinEnd = 3.20f;
        private const float MatchOverlayStart = 3.20f;
        private const float MatchOverlaySolid = 3.80f;
        private const float ExitFadeStart = 4.05f;
        private const float SceneSwapTime = 4.45f;
        private const float MatchOverlayRelease = 5.30f;
        private const float IntroEnd = 5.80f;

        private readonly List<UnityEngine.Object> _runtimeResources = new List<UnityEngine.Object>();
        private readonly List<Camera> _suppressedCameras = new List<Camera>();
        private readonly BrandIntroPlaybackGate _playbackGate =
            new BrandIntroPlaybackGate(VisibleWarmupFrames);
        private Camera _introCamera;
        private Transform _coin;
        private Renderer _coinRenderer;
        private Texture2D _matchTexture;
        private ReplayApplicationRoot _underlyingApplication;
        private GUIStyle _titleStyle;
        private float _elapsed;
        private float _blackAlpha = 1f;
        private float _matchCutAlpha;
        private float _previewHold;
        private bool _previewLoop;
        private bool _sceneRevealed;
        private bool _loggedFirstUpdate;
        private bool _loggedFirstGui;
        private bool _loggedPlaybackStart;
        private string _stageError;

        private float ExitFadeStartTime => ExitFadeStart + _previewHold;
        private float SceneSwapTimeValue => SceneSwapTime + _previewHold;
        private float MatchOverlayReleaseTime => MatchOverlayRelease + _previewHold;
        private float IntroEndTime => IntroEnd + _previewHold;

        private void Awake()
        {
            BrandIntroGraphicMatch.ResetViewportWidth();
            gameObject.layer = IntroLayer;
            if (Array.Exists(
                    Environment.GetCommandLineArgs(),
                    argument => string.Equals(
                        argument,
                        "--preview-brand-intro",
                        StringComparison.OrdinalIgnoreCase)))
                _previewLoop = true;
#if UNITY_EDITOR
            if (PlayerPrefs.GetInt(BrandIntroBootstrap.PreviewHoldPrefKey, 0) == 1)
            {
                _previewHold = 30f;
                PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewHoldPrefKey);
                PlayerPrefs.Save();
            }
            if (PlayerPrefs.GetInt(BrandIntroBootstrap.PreviewLoopPrefKey, 0) == 1)
            {
                _previewLoop = true;
                PlayerPrefs.DeleteKey(BrandIntroBootstrap.PreviewLoopPrefKey);
                PlayerPrefs.Save();
            }
#endif
            try
            {
                BuildStage();
                Debug.Log("[BrandIntro] Runtime stage created successfully.");
            }
            catch (Exception exception)
            {
                _stageError = exception.ToString();
                Debug.LogException(exception);
            }
        }

        private IEnumerator Start()
        {
            yield return null;
            SuppressUnderlyingApplication();
        }

        private void Update()
        {
            if (!_loggedFirstUpdate)
            {
                _loggedFirstUpdate = true;
                Debug.Log($"[BrandIntro] First Update. active={isActiveAndEnabled}; camera={_introCamera != null && _introCamera.enabled}");
            }
            if (!_sceneRevealed)
            {
                SuppressUnderlyingApplication();
                SuppressUnderlyingCameras();
            }

            // Unity can tick the first scene while its native splash still covers
            // the player, or while the launched window is not yet focused. Hold
            // frame zero until the branded shot has been visibly stable, then
            // pause rather than skip whenever the player loses focus.
            if (!_playbackGate.ShouldAdvance(
                    IsNativeSplashFinished(),
                    IsPresentationWindowFocused()))
            {
                if (!_playbackGate.HasStarted)
                    ResetOpeningVisualState();
                return;
            }
            if (!_loggedPlaybackStart)
            {
                _loggedPlaybackStart = true;
                Debug.Log("[BrandIntro] Visible player confirmed; animation clock started.");
            }

            // Window focus clicks and ordinary mouse movement must not erase the
            // opening shot. Skipping unlocks only after the coin has completed its
            // rotation and only on an explicit keyboard command.
            if (!_previewLoop
                && _elapsed >= SkipInputUnlockTime
                && (Input.GetKeyDown(KeyCode.Escape)
                    || Input.GetKeyDown(KeyCode.Space)
                    || Input.GetKeyDown(KeyCode.Return)
                    || Input.GetKeyDown(KeyCode.KeypadEnter)))
                _elapsed = Mathf.Max(_elapsed, ExitFadeStartTime);
            else
                _elapsed += Time.unscaledDeltaTime;

            AnimateCoin();

            // Editor-only inspection mode intentionally never reveals the scene
            // or destroys the splash. It keeps rotating until Play Mode is stopped.
            if (_previewLoop)
            {
                _matchCutAlpha = 0f;
                _blackAlpha = _elapsed < FadeFromBlackEnd
                    ? 1f - SmoothStep(0f, FadeFromBlackEnd, _elapsed)
                    : 0f;
                return;
            }

            _matchCutAlpha = SmoothStep(MatchOverlayStart, MatchOverlaySolid, _elapsed)
                             * (1f - SmoothStep(MatchOverlayReleaseTime, IntroEndTime, _elapsed));

            if (_elapsed < FadeFromBlackEnd)
                _blackAlpha = 1f - SmoothStep(0f, FadeFromBlackEnd, _elapsed);
            else
                _blackAlpha = 0f;

            if (!_sceneRevealed && _elapsed >= SceneSwapTimeValue)
                RevealUnderlyingScene();
            if (_elapsed >= IntroEndTime)
                Destroy(gameObject);
        }

        private void OnGUI()
        {
            if (!_loggedFirstGui)
            {
                _loggedFirstGui = true;
                Debug.Log("[BrandIntro] First OnGUI.");
            }
            GUI.depth = -10000;
            EnsureStyles();
            if (!string.IsNullOrWhiteSpace(_stageError))
            {
                var previousColor = GUI.color;
                GUI.color = new Color(0.008f, 0.014f, 0.032f, 1f);
                GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Screen.height), Texture2D.whiteTexture);
                GUI.color = Color.white;
                GUI.Label(
                    new Rect(0f, Screen.height * 0.42f, Screen.width, Screen.height * 0.16f),
                    "GENWORLD\nBRAND INTRO INITIALIZATION FAILED",
                    _titleStyle);
                GUI.color = previousColor;
                return;
            }
            if (_matchTexture != null && _matchCutAlpha > 0.001f)
            {
                var matchRect = BrandIntroGraphicMatch.CreateArtworkRect(
                    CalculateCoinScreenBounds(),
                    _matchTexture.width / (float)_matchTexture.height);
                var previous = GUI.color;
                DrawMatchMatte(matchRect, _matchCutAlpha);
                GUI.color = new Color(1f, 1f, 1f, _matchCutAlpha);
                GUI.DrawTexture(
                    matchRect,
                    _matchTexture,
                    ScaleMode.StretchToFill,
                    true);
                GUI.color = previous;
            }

            if (_blackAlpha <= 0.001f)
                return;
            var color = GUI.color;
            GUI.color = new Color(0.008f, 0.014f, 0.032f, _blackAlpha);
            GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Screen.height), Texture2D.whiteTexture);
            GUI.color = color;
        }

        private void OnDestroy()
        {
            Debug.Log($"[BrandIntro] Destroyed at elapsed={_elapsed:0.000}; revealed={_sceneRevealed}.");
            if (!_sceneRevealed && _underlyingApplication != null)
                _underlyingApplication.enabled = true;
            RestoreUnderlyingCameras();
            foreach (var resource in _runtimeResources)
            {
                if (resource != null)
                    Destroy(resource);
            }
            _runtimeResources.Clear();
        }

        private void BuildStage()
        {
            _introCamera = CreateCamera();
            BuildIntroLook();
            BuildLighting();
            BuildCoin();
        }

        private Camera CreateCamera()
        {
            var cameraObject = CreateChild("Brand Intro Camera");
            cameraObject.transform.position = new Vector3(0f, 0.20f, -8.5f);
            cameraObject.transform.rotation = Quaternion.LookRotation(
                new Vector3(0f, 0.25f, 0f) - cameraObject.transform.position,
                Vector3.up);
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.008f, 0.014f, 0.032f);
            camera.cullingMask = 1 << IntroLayer;
            camera.depth = 100f;
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 80f;
            HdrpStationLook.ConfigureCamera(camera);
            var additional = camera.GetComponent<HDAdditionalCameraData>();
            if (additional != null)
            {
                additional.volumeLayerMask = 1 << IntroLayer;
                additional.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;
                additional.backgroundColorHDR = new Color(0.00003f, 0.000055f, 0.00012f, 1f);
                additional.clearDepth = true;
            }
            return camera;
        }

        private void BuildIntroLook()
        {
            var volumeObject = CreateChild("Brand Intro HDRP Look");
            var volume = volumeObject.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 500f;
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            profile.name = "GenWorld brand intro look";
            volume.sharedProfile = profile;
            _runtimeResources.Add(profile);

            var exposure = profile.Add<Exposure>(true);
            exposure.mode.Override(ExposureMode.Fixed);
            exposure.fixedExposure.Override(0f);
            var color = profile.Add<ColorAdjustments>(true);
            color.contrast.Override(6f);
            color.saturation.Override(0f);
            var tonemapping = profile.Add<Tonemapping>(true);
            tonemapping.mode.Override(TonemappingMode.ACES);
            var bloom = profile.Add<Bloom>(true);
            bloom.intensity.Override(BrandIntroBootstrap.IntroBloomIntensity);
            bloom.threshold.Override(BrandIntroBootstrap.IntroBloomThreshold);
            bloom.scatter.Override(BrandIntroBootstrap.IntroBloomScatter);
            var vignette = profile.Add<Vignette>(true);
            vignette.intensity.Override(0.30f);
            vignette.smoothness.Override(0.72f);
        }

        private void BuildLighting()
        {
            AddSpotLight(
                "Perseus cool key",
                new Vector3(-3.2f, 3.5f, -4.5f),
                new Color(0.42f, 0.70f, 1f),
                0.30f,
                38f,
                false);
            AddSpotLight(
                "GenWorld cyan rim",
                new Vector3(3.6f, 1.8f, 2.4f),
                new Color(0.05f, 0.58f, 0.92f),
                0.45f,
                34f,
                false);
            AddSpotLight(
                "GenWorld lime fill",
                new Vector3(-2.4f, -1.2f, -2.8f),
                new Color(0.48f, 0.72f, 0.18f),
                0.08f,
                52f,
                false);
        }

        private void AddSpotLight(
            string name,
            Vector3 position,
            Color color,
            float intensity,
            float angle,
            bool shadows)
        {
            var lightObject = CreateChild(name);
            lightObject.transform.position = position;
            lightObject.transform.rotation = Quaternion.LookRotation(
                new Vector3(0f, 0.25f, 0f) - position,
                Vector3.up);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Spot;
            light.color = color;
            light.intensity = intensity;
            light.range = 16f;
            light.spotAngle = angle;
            light.innerSpotAngle = angle * 0.62f;
            light.shadows = shadows ? LightShadows.Soft : LightShadows.None;
            light.shadowStrength = 0.72f;
            light.cullingMask = 1 << IntroLayer;
            HdrpStationLook.EnsureAdditionalLightData(light);
        }

        private void BuildCoin()
        {
            var coinObject = CreateChild("Rotating GenWorld Coin");
            _coin = coinObject.transform;
            _coin.localPosition = new Vector3(0f, 0.33f, 0f);

            var mesh = BrandIntroCoinMesh.Create(1.62f, 0.30f, 112);
            _runtimeResources.Add(mesh);
            coinObject.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = coinObject.AddComponent<MeshRenderer>();
            _coinRenderer = renderer;
            var frontTexture = Resources.Load<Texture2D>("BrandIntro/perseus-team");
            _matchTexture = frontTexture;
            if (frontTexture != null)
                frontTexture.wrapMode = TextureWrapMode.Clamp;
            var edge = CreateLit(
                "Brand intro graphite edge",
                new Color(0.025f, 0.07f, 0.12f),
                0.22f,
                0.26f);
            var front = CreateUnlit(
                "Perseus coin face",
                Color.white,
                frontTexture);
            if (frontTexture != null)
            {
                var textureProperty = front.HasProperty("_UnlitColorMap")
                    ? "_UnlitColorMap"
                    : front.HasProperty("_BaseColorMap")
                        ? "_BaseColorMap"
                        : "_MainTex";
                var aspect = frontTexture.width / (float)frontTexture.height;
                front.SetTextureScale(textureProperty, new Vector2(1f, aspect));
                front.SetTextureOffset(textureProperty, new Vector2(0f, (1f - aspect) * 0.5f));
            }
            var hiroshimaLogo = Resources.Load<Texture2D>(
                "BrandIntro/hiroshima-university-logo");
            var backTexture = CreateHiroshimaUniversityBackTexture(hiroshimaLogo);
            var back = CreateUnlit(
                "Hiroshima University coin face",
                Color.white,
                backTexture);
            renderer.sharedMaterials = new[] { edge, front, back };
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;

            var rimMaterial = CreateUnlit(
                "Brand intro electric cyan rim",
                new Color(0.002f, 0.015f, 0.025f));
            AddRim("Perseus luminous rim", -0.158f, 1.51f, 0.026f, rimMaterial);
            AddRim("GenWorld luminous rim", 0.158f, 1.51f, 0.026f, rimMaterial);
        }

        private void AddRim(string name, float z, float radius, float thickness, Material material)
        {
            var rim = new GameObject(name);
            rim.layer = IntroLayer;
            rim.transform.SetParent(_coin, false);
            rim.transform.localPosition = Vector3.forward * z;
            var mesh = BrandIntroCoinMesh.CreateTorus(radius, thickness, 112, 10);
            _runtimeResources.Add(mesh);
            rim.AddComponent<MeshFilter>().sharedMesh = mesh;
            var renderer = rim.AddComponent<MeshRenderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = ShadowCastingMode.Off;
            renderer.receiveShadows = false;
        }

        private void AnimateCoin()
        {
            if (_coin == null)
                return;

            // Begin edge-on, rotate 450 degrees (1.25 turns), then land exactly
            // face-on. The coin deliberately keeps its final size: the station
            // artwork is framed to this same screen width for the graphic match.
            var animationTime = _previewLoop
                ? Mathf.Repeat(_elapsed, SpinEnd + 0.65f)
                : _elapsed;
            var spin = SmoothStep(SpinStart, SpinEnd, animationTime);
            var easeOut = spin;
            var yRotation = Mathf.Lerp(-90f, 360f, easeOut);
            var wobble = Mathf.Sin(spin * Mathf.PI * 6f) * (1f - spin);
            var xRotation = Mathf.Lerp(-12f, 0f, easeOut) + wobble * 6f;
            var zRotation = Mathf.Lerp(-6f, 0f, easeOut) - wobble * 2.5f;
            _coin.localRotation = Quaternion.Euler(xRotation, yRotation, zRotation);

            var entrance = SmoothStep(0f, 0.78f, animationTime);
            var settle = 1f + Mathf.Sin(Mathf.Clamp01(spin) * Mathf.PI) * 0.055f;
            _coin.localScale = Vector3.one
                               * Mathf.Lerp(0.72f, 1f, entrance)
                               * settle;
            var approach = SmoothStep(0f, 0.95f, animationTime);
            _coin.localPosition = new Vector3(
                0f,
                0.33f + Mathf.Sin(animationTime * 2.15f) * 0.045f,
                Mathf.Lerp(1.15f, 0f, approach));
        }

        private Rect CalculateCoinScreenBounds()
        {
            if (_introCamera == null || _coinRenderer == null || Screen.width < 1 || Screen.height < 1)
            {
                var fallbackWidth = Screen.width * BrandIntroGraphicMatch.DefaultViewportWidth;
                return new Rect(
                    (Screen.width - fallbackWidth) * 0.5f,
                    (Screen.height - fallbackWidth) * 0.5f,
                    fallbackWidth,
                    fallbackWidth);
            }

            var bounds = _coinRenderer.bounds;
            var min = new Vector2(float.PositiveInfinity, float.PositiveInfinity);
            var max = new Vector2(float.NegativeInfinity, float.NegativeInfinity);
            for (var x = -1; x <= 1; x += 2)
            {
                for (var y = -1; y <= 1; y += 2)
                {
                    for (var z = -1; z <= 1; z += 2)
                    {
                        var world = bounds.center + Vector3.Scale(
                            bounds.extents,
                            new Vector3(x, y, z));
                        var screen = _introCamera.WorldToScreenPoint(world);
                        if (screen.z <= 0f)
                            continue;
                        min = Vector2.Min(min, new Vector2(screen.x, screen.y));
                        max = Vector2.Max(max, new Vector2(screen.x, screen.y));
                    }
                }
            }

            if (float.IsInfinity(min.x) || max.x <= min.x || max.y <= min.y)
            {
                var fallbackWidth = Screen.width * BrandIntroGraphicMatch.DefaultViewportWidth;
                return new Rect(
                    (Screen.width - fallbackWidth) * 0.5f,
                    (Screen.height - fallbackWidth) * 0.5f,
                    fallbackWidth,
                    fallbackWidth);
            }

            return new Rect(
                min.x,
                Screen.height - max.y,
                max.x - min.x,
                max.y - min.y);
        }

        private static void DrawMatchMatte(Rect window, float alpha)
        {
            GUI.color = new Color(0.008f, 0.014f, 0.032f, alpha);
            GUI.DrawTexture(new Rect(0f, 0f, Screen.width, Mathf.Max(0f, window.y)), Texture2D.whiteTexture);
            GUI.DrawTexture(new Rect(0f, window.yMax, Screen.width, Mathf.Max(0f, Screen.height - window.yMax)), Texture2D.whiteTexture);
            GUI.DrawTexture(new Rect(0f, window.y, Mathf.Max(0f, window.x), window.height), Texture2D.whiteTexture);
            GUI.DrawTexture(new Rect(window.xMax, window.y, Mathf.Max(0f, Screen.width - window.xMax), window.height), Texture2D.whiteTexture);
        }

        private void ResetOpeningVisualState()
        {
            _elapsed = 0f;
            _blackAlpha = 1f;
            _matchCutAlpha = 0f;
            AnimateCoin();
        }

        private static bool IsNativeSplashFinished()
        {
#if UNITY_EDITOR
            return true;
#else
            return SplashScreen.isFinished;
#endif
        }

        private static bool IsPresentationWindowFocused()
        {
#if UNITY_EDITOR
            return true;
#else
            return UnityEngine.Application.isFocused;
#endif
        }

        private Texture2D CreateHiroshimaUniversityBackTexture(Texture2D officialLogo)
        {
            if (officialLogo == null)
                throw new InvalidOperationException(
                    "The high-resolution Hiroshima University logo texture is unavailable.");
            if (!officialLogo.isReadable)
                throw new InvalidOperationException(
                    "The Hiroshima University logo must have Read/Write enabled.");

            const int size = 1024;
            const int padding = 28;
            var texture = new Texture2D(size, size, TextureFormat.RGBA32, true)
            {
                name = "Hiroshima University crest coin back",
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Trilinear,
                anisoLevel = 8
            };

            var sourcePixels = officialLogo.GetPixels32();
            var crestBounds = BrandIntroCrestLayout.FindCenteredSquare(
                sourcePixels,
                officialLogo.width,
                officialLogo.height);
            var pixels = new Color32[size * size];
            var innerSize = size - padding * 2;
            for (var y = 0; y < size; y++)
            {
                for (var x = 0; x < size; x++)
                {
                    var nx = (x - size * 0.5f) / (size * 0.5f);
                    var ny = (y - size * 0.5f) / (size * 0.5f);
                    var radial = Mathf.Clamp01(nx * nx + ny * ny);
                    var background = Color.Lerp(
                        new Color(0.550f, 0.700f, 0.580f, 1f),
                        new Color(0.220f, 0.340f, 0.260f, 1f),
                        radial);

                    var composed = background;
                    if (x >= padding && x < size - padding
                        && y >= padding && y < size - padding)
                    {
                        var u = (x - padding) / (innerSize - 1f);
                        var v = (y - padding) / (innerSize - 1f);
                        var sourceU = (
                            crestBounds.x + u * (crestBounds.width - 1f) + 0.5f)
                            / officialLogo.width;
                        var sourceV = (
                            crestBounds.y + v * (crestBounds.height - 1f) + 0.5f)
                            / officialLogo.height;
                        var sample = officialLogo.GetPixelBilinear(sourceU, sourceV);
                        composed = Color.Lerp(background, sample, sample.a);
                    }

                    pixels[y * size + x] = composed;
                }
            }

            texture.SetPixels32(pixels);
            texture.Apply(true, false);
            _runtimeResources.Add(texture);
            return texture;
        }

        private static void DrawWindowGrid(
            Color32[] pixels,
            int size,
            int x,
            int y,
            int width,
            int height,
            int columns,
            int rows,
            Color32 color)
        {
            var cellWidth = width / columns;
            var cellHeight = height / rows;
            for (var row = 0; row < rows; row++)
            {
                for (var column = 0; column < columns; column++)
                {
                    FillRect(
                        pixels,
                        size,
                        x + column * cellWidth + 5,
                        y + row * cellHeight + 6,
                        Mathf.Max(4, cellWidth - 10),
                        Mathf.Max(4, cellHeight - 12),
                        color);
                }
            }
        }

        private static void FillRect(
            Color32[] pixels,
            int size,
            int x,
            int y,
            int width,
            int height,
            Color32 color)
        {
            for (var row = Mathf.Max(0, y); row < Mathf.Min(size, y + height); row++)
            {
                for (var column = Mathf.Max(0, x); column < Mathf.Min(size, x + width); column++)
                    pixels[row * size + column] = color;
            }
        }

        private Material CreateLit(
            string name,
            Color color,
            float metallic,
            float smoothness,
            Texture texture = null)
        {
            var shader = Shader.Find("HDRP/Lit") ?? Shader.Find("Standard");
            if (shader == null)
                throw new InvalidOperationException("A compatible lit shader is unavailable.");
            var material = new Material(shader) { name = name, enableInstancing = true };
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
            if (material.HasProperty("_Metallic"))
                material.SetFloat("_Metallic", metallic);
            if (material.HasProperty("_Smoothness"))
                material.SetFloat("_Smoothness", smoothness);
            if (material.HasProperty("_Glossiness"))
                material.SetFloat("_Glossiness", smoothness);
            if (texture != null)
            {
                material.mainTexture = texture;
                if (material.HasProperty("_BaseColorMap"))
                    material.SetTexture("_BaseColorMap", texture);
            }
            if (material.HasProperty("_DoubleSidedEnable"))
                material.SetFloat("_DoubleSidedEnable", 1f);
            material.EnableKeyword("_DOUBLESIDED_ON");
            material.doubleSidedGI = true;
            if (shader.name == "HDRP/Lit")
            {
                // HDRP derives shader passes and keywords from these serialized
                // properties. Runtime-created materials need the same validation
                // the Inspector performs, otherwise individual passes can render
                // with the magenta error shader on alternating frames.
                if (material.HasProperty("_SurfaceType"))
                    material.SetFloat("_SurfaceType", 0f);
                if (material.HasProperty("_AlphaCutoffEnable"))
                    material.SetFloat("_AlphaCutoffEnable", 0f);
                if (material.HasProperty("_ZWrite"))
                    material.SetFloat("_ZWrite", 1f);
                HDMaterial.ValidateMaterial(material);
            }
            _runtimeResources.Add(material);
            return material;
        }

        private Material CreateUnlit(string name, Color color, Texture texture = null)
        {
            var shader = Shader.Find("HDRP/Unlit") ?? Shader.Find("Unlit/Texture");
            if (shader == null)
                throw new InvalidOperationException("A compatible unlit shader is unavailable.");

            var material = new Material(shader) { name = name, enableInstancing = true };
            if (material.HasProperty("_UnlitColor"))
                material.SetColor("_UnlitColor", color);
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
            if (texture != null)
            {
                material.mainTexture = texture;
                if (material.HasProperty("_UnlitColorMap"))
                    material.SetTexture("_UnlitColorMap", texture);
                if (material.HasProperty("_BaseColorMap"))
                    material.SetTexture("_BaseColorMap", texture);
            }
            if (material.HasProperty("_EmissiveColor"))
                material.SetColor("_EmissiveColor", Color.black);
            if (material.HasProperty("_DoubleSidedEnable"))
                material.SetFloat("_DoubleSidedEnable", 1f);
            material.EnableKeyword("_DOUBLESIDED_ON");
            material.doubleSidedGI = true;
            if (shader.name == "HDRP/Unlit")
            {
                if (material.HasProperty("_SurfaceType"))
                    material.SetFloat("_SurfaceType", 0f);
                if (material.HasProperty("_AlphaCutoffEnable"))
                    material.SetFloat("_AlphaCutoffEnable", 0f);
                if (material.HasProperty("_ZWrite"))
                    material.SetFloat("_ZWrite", 1f);
                HDMaterial.ValidateMaterial(material);
            }
            _runtimeResources.Add(material);
            return material;
        }

        private Material CreateEmissive(string name, Color color, float intensity)
        {
            var material = CreateLit(name, color, 0.55f, 0.84f);
            material.EnableKeyword("_EMISSION");
            if (material.HasProperty("_EmissionColor"))
                material.SetColor("_EmissionColor", color * intensity);
            if (material.HasProperty("_EmissiveColor"))
                material.SetColor("_EmissiveColor", color * intensity);
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
            if (material.shader.name == "HDRP/Lit")
                HDMaterial.ValidateMaterial(material);
            return material;
        }

        private GameObject CreateChild(string name)
        {
            var child = new GameObject(name) { layer = IntroLayer };
            child.transform.SetParent(transform, false);
            return child;
        }

        private void SuppressUnderlyingApplication()
        {
            if (_underlyingApplication == null)
                _underlyingApplication = UnityEngine.Object.FindFirstObjectByType<ReplayApplicationRoot>();
            if (_underlyingApplication != null && _underlyingApplication.enabled)
                _underlyingApplication.enabled = false;
        }

        private void RevealUnderlyingScene()
        {
            // The replay application is constructed only after the Perseus artwork
            // covers the frame. The station camera starts on that exact same image,
            // so disabling the intro camera becomes a graphic match instead of a cut.
            var coinScreenBounds = CalculateCoinScreenBounds();
            BrandIntroGraphicMatch.CaptureViewportWidth(
                coinScreenBounds.width / Mathf.Max(1f, Screen.width));
            _underlyingApplication = ReplayBootstrap.EnsureApplicationCreated();
            _sceneRevealed = true;
            if (_introCamera != null)
                _introCamera.enabled = false;
            RestoreUnderlyingCameras();
            if (_underlyingApplication != null)
                _underlyingApplication.enabled = true;
        }

        private void SuppressUnderlyingCameras()
        {
            var cameras = UnityEngine.Object.FindObjectsByType<Camera>(
                FindObjectsInactive.Exclude,
                FindObjectsSortMode.None);
            foreach (var camera in cameras)
            {
                if (camera == null || camera == _introCamera || !camera.enabled)
                    continue;
                if (!_suppressedCameras.Contains(camera))
                    _suppressedCameras.Add(camera);
                camera.enabled = false;
            }
        }

        private void RestoreUnderlyingCameras()
        {
            foreach (var camera in _suppressedCameras)
            {
                if (camera != null)
                    camera.enabled = true;
            }
            _suppressedCameras.Clear();
        }

        private void EnsureStyles()
        {
            if (_titleStyle != null)
                return;
            _titleStyle = new GUIStyle(GUI.skin.label)
            {
                alignment = TextAnchor.MiddleCenter,
                fontSize = Mathf.Clamp(Mathf.RoundToInt(Screen.height * 0.067f), 32, 72),
                fontStyle = FontStyle.Bold,
                normal = { textColor = Color.white }
            };
        }

        private static float SmoothStep(float start, float end, float value)
        {
            if (end <= start)
                return value >= end ? 1f : 0f;
            return Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(start, end, value));
        }
    }
}
