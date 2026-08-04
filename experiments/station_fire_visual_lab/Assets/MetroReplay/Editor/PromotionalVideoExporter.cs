using System;
using System.IO;
using MetroReplay.Presentation;
using UnityEditor;
using UnityEditor.Recorder;
using UnityEditor.Recorder.Encoder;
using UnityEditor.Recorder.Input;
using UnityEngine;

namespace MetroReplay.Editor
{
    [InitializeOnLoad]
    public static class PromotionalVideoExporter
    {
        private const string PendingSessionKey = "MetroReplay.PromotionalVideoCapture.Pending";
        private const string OutputBaseSessionKey = "MetroReplay.PromotionalVideoCapture.OutputBase";
        private const string CompletedOutputSessionKey = "MetroReplay.PromotionalVideoCapture.CompletedOutput";
        private const string QuitAfterCaptureSessionKey = "MetroReplay.PromotionalVideoCapture.QuitEditor";
        private const string CommandLineStartedSessionKey = "MetroReplay.PromotionalVideoCapture.CommandLineStarted";
        private const string CommandLineArgument = "--export-promotional-video";
        private const string BackgroundMusicAssetPath =
            "Assets/MetroReplay/Editor/Audio/House02_LilyJ_Mixkit.mp3";
        private static RecorderController _recorderController;
        private static AudioSource _backgroundMusicSource;
        private static AudioListener _temporaryAudioListener;
        private static bool _commandLineExportRequested;
        private static bool _recordingStarted;
        private static double _recordingStartedAt;

        static PromotionalVideoExporter()
        {
            EditorApplication.playModeStateChanged -= HandlePlayModeStateChanged;
            EditorApplication.playModeStateChanged += HandlePlayModeStateChanged;

            if (!SessionState.GetBool(PendingSessionKey, false)
                && !EditorApplication.isPlayingOrWillChangePlaymode
                && PromotionalVideoCapture.IsActive)
                PromotionalVideoCapture.SetActive(false);

            EditorApplication.delayCall += RevealCompletedOutput;
        }

        [InitializeOnLoadMethod]
        private static void ScheduleCommandLineExport()
        {
            if (!HasCommandLineExportArgument())
                return;

            if (SessionState.GetBool(PendingSessionKey, false)
                || !string.IsNullOrWhiteSpace(
                    SessionState.GetString(CompletedOutputSessionKey, string.Empty)))
                return;

            if (!SessionState.GetBool(CommandLineStartedSessionKey, false))
            {
                SessionState.SetBool(CommandLineStartedSessionKey, true);
                Debug.Log("[PromotionalVideo] Command-line export scheduled.");
            }

            _commandLineExportRequested = true;
            EditorApplication.update -= TryStartCommandLineExport;
            EditorApplication.update += TryStartCommandLineExport;
        }

        private static void TryStartCommandLineExport()
        {
            if (!_commandLineExportRequested)
            {
                EditorApplication.update -= TryStartCommandLineExport;
                return;
            }

            if (EditorApplication.isCompiling
                || EditorApplication.isUpdating
                || EditorApplication.isPlayingOrWillChangePlaymode)
                return;

            EditorApplication.update -= TryStartCommandLineExport;
            Export();
        }

        [MenuItem("Metro Replay/视频/导出 26 秒宣传片 MP4", priority = 200)]
        public static void Export()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog("无法开始录制", "请先退出 Play Mode，再导出宣传片。", "确定");
                return;
            }

            var outputDirectory = Path.GetFullPath(
                Path.Combine(UnityEngine.Application.dataPath, "..", "Recordings"));
            Directory.CreateDirectory(outputDirectory);
            var fileName = $"PerseusMetro_{DateTime.Now:yyyyMMdd_HHmmss_fff}";
            var outputBase = Path.Combine(outputDirectory, fileName);

            SessionState.SetString(OutputBaseSessionKey, outputBase);
            SessionState.SetBool(PendingSessionKey, true);
            SessionState.SetString(CompletedOutputSessionKey, string.Empty);
            SessionState.SetBool(
                QuitAfterCaptureSessionKey,
                _commandLineExportRequested || HasCommandLineExportArgument());
            _commandLineExportRequested = false;
            PromotionalVideoCapture.SetActive(true);

            Debug.Log(
                $"[PromotionalVideo] Preparing {PromotionalVideoCapture.DurationSeconds:0.#} second export: "
                + outputBase + ".mp4");
            EditorApplication.ExecuteMenuItem("Window/General/Game");
            EditorApplication.EnterPlaymode();
        }

        [MenuItem("Metro Replay/视频/导出 26 秒宣传片 MP4", true)]
        private static bool ValidateExport()
        {
            return !EditorApplication.isPlayingOrWillChangePlaymode
                   && !SessionState.GetBool(PendingSessionKey, false);
        }

        public static void ExportFromCommandLine()
        {
            _commandLineExportRequested = true;
            EditorApplication.delayCall += Export;
        }

        private static bool HasCommandLineExportArgument()
        {
            return Array.Exists(
                Environment.GetCommandLineArgs(),
                argument => string.Equals(
                    argument,
                    CommandLineArgument,
                    StringComparison.OrdinalIgnoreCase));
        }

        private static void HandlePlayModeStateChanged(PlayModeStateChange state)
        {
            if (!SessionState.GetBool(PendingSessionKey, false))
                return;

            switch (state)
            {
                case PlayModeStateChange.EnteredPlayMode:
                    StartRecording();
                    break;
                case PlayModeStateChange.ExitingPlayMode:
                    CompleteRecording();
                    break;
            }
        }

        private static void StartRecording()
        {
            try
            {
                var outputBase = SessionState.GetString(OutputBaseSessionKey, string.Empty);
                if (string.IsNullOrWhiteSpace(outputBase))
                    throw new InvalidOperationException("The promotional video output path is missing.");

                PrepareBackgroundMusic();

                var controllerSettings = ScriptableObject.CreateInstance<RecorderControllerSettings>();
                controllerSettings.SetRecordModeToTimeInterval(
                    0f,
                    PromotionalVideoCapture.DurationSeconds);
                controllerSettings.FrameRatePlayback = FrameRatePlayback.Constant;
                controllerSettings.FrameRate = PromotionalVideoCapture.FrameRate;
                controllerSettings.CapFrameRate = true;
                controllerSettings.ExitPlayMode = true;

                var movieSettings = ScriptableObject.CreateInstance<MovieRecorderSettings>();
                movieSettings.name = "Metro Replay 26 Second Promotional Video";
                movieSettings.Enabled = true;
                movieSettings.EncoderSettings = new CoreEncoderSettings
                {
                    Codec = CoreEncoderSettings.OutputCodec.MP4,
                    EncodingQuality = CoreEncoderSettings.VideoEncodingQuality.High
                };
                movieSettings.CaptureAudio = true;
                movieSettings.CaptureAlpha = false;
                movieSettings.ImageInputSettings = new GameViewInputSettings
                {
                    OutputWidth = PromotionalVideoCapture.OutputWidth,
                    OutputHeight = PromotionalVideoCapture.OutputHeight
                };
                movieSettings.OutputFile = outputBase;

                controllerSettings.AddRecorderSettings(movieSettings);
                RecorderOptions.VerboseMode = false;
                _recorderController = new RecorderController(controllerSettings);
                _recorderController.PrepareRecording();
                if (!_recorderController.StartRecording())
                    throw new InvalidOperationException(
                        "Unity Recorder could not start. Check the Console for recorder validation errors.");
                _recordingStarted = true;
                _recordingStartedAt = EditorApplication.timeSinceStartup;
                StartBackgroundMusic();
                EditorApplication.update -= MonitorRecordingCompletion;
                EditorApplication.update += MonitorRecordingCompletion;

                Debug.Log(
                    $"[PromotionalVideo] Recording started at {PromotionalVideoCapture.OutputWidth}x"
                    + $"{PromotionalVideoCapture.OutputHeight}, {PromotionalVideoCapture.FrameRate} FPS; "
                    + $"background music starts at {PromotionalVideoCapture.BackgroundMusicStartSeconds:0.#}s "
                    + $"with {PromotionalVideoCapture.BackgroundMusicPeakVolume:P0} peak volume.");
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                AbortRecording();
            }
        }

        private static void MonitorRecordingCompletion()
        {
            if (!_recordingStarted || _recorderController == null || !EditorApplication.isPlaying)
                return;

            var elapsedSeconds = (float)(EditorApplication.timeSinceStartup - _recordingStartedAt);
            if (_backgroundMusicSource != null)
                _backgroundMusicSource.volume =
                    PromotionalVideoCapture.EvaluateBackgroundMusicVolume(elapsedSeconds);

            if (_recorderController.IsRecording())
                return;

            _recordingStarted = false;
            StopBackgroundMusic();
            EditorApplication.update -= MonitorRecordingCompletion;
            Debug.Log("[PromotionalVideo] Recorder reached the requested duration; exiting Play Mode.");
            EditorApplication.ExitPlaymode();
        }

        private static void CompleteRecording()
        {
            EditorApplication.update -= MonitorRecordingCompletion;
            _recordingStarted = false;
            if (_recorderController != null && _recorderController.IsRecording())
                _recorderController.StopRecording();
            StopBackgroundMusic();

            var outputBase = SessionState.GetString(OutputBaseSessionKey, string.Empty);
            var outputFile = string.IsNullOrWhiteSpace(outputBase) ? string.Empty : outputBase + ".mp4";
            SessionState.SetString(CompletedOutputSessionKey, outputFile);
            SessionState.SetBool(PendingSessionKey, false);
            PromotionalVideoCapture.SetActive(false);
            _recorderController = null;

            if (!string.IsNullOrWhiteSpace(outputFile))
                Debug.Log("[PromotionalVideo] Recording finished: " + outputFile);

            EditorApplication.delayCall -= RevealCompletedOutput;
            EditorApplication.delayCall += RevealCompletedOutput;
        }

        private static void AbortRecording()
        {
            EditorApplication.update -= MonitorRecordingCompletion;
            _recordingStarted = false;
            if (_recorderController != null && _recorderController.IsRecording())
                _recorderController.StopRecording();
            StopBackgroundMusic();
            _recorderController = null;
            SessionState.SetBool(PendingSessionKey, false);
            SessionState.SetString(CompletedOutputSessionKey, string.Empty);
            PromotionalVideoCapture.SetActive(false);
            if (EditorApplication.isPlaying)
                EditorApplication.ExitPlaymode();
        }

        private static void PrepareBackgroundMusic()
        {
            StopBackgroundMusic();
            var clip = AssetDatabase.LoadAssetAtPath<AudioClip>(BackgroundMusicAssetPath);
            if (clip == null)
                throw new FileNotFoundException(
                    "The promotional background music could not be loaded.",
                    BackgroundMusicAssetPath);

            var musicObject = new GameObject("Promotional Video Background Music")
            {
                hideFlags = HideFlags.HideAndDontSave
            };
            _backgroundMusicSource = musicObject.AddComponent<AudioSource>();
            _backgroundMusicSource.clip = clip;
            _backgroundMusicSource.playOnAwake = false;
            _backgroundMusicSource.loop = false;
            _backgroundMusicSource.spatialBlend = 0f;
            _backgroundMusicSource.volume = 0f;
            _backgroundMusicSource.priority = 64;

            if (UnityEngine.Object.FindFirstObjectByType<AudioListener>() == null)
                _temporaryAudioListener = musicObject.AddComponent<AudioListener>();
        }

        private static void StartBackgroundMusic()
        {
            if (_backgroundMusicSource == null || _backgroundMusicSource.clip == null)
                throw new InvalidOperationException("The promotional background music is not prepared.");

            var latestSafeStart = Mathf.Max(0f, _backgroundMusicSource.clip.length - 0.01f);
            _backgroundMusicSource.time = Mathf.Min(
                PromotionalVideoCapture.BackgroundMusicStartSeconds,
                latestSafeStart);
            _backgroundMusicSource.volume = 0f;
            _backgroundMusicSource.Play();
        }

        private static void StopBackgroundMusic()
        {
            if (_backgroundMusicSource != null)
            {
                var musicObject = _backgroundMusicSource.gameObject;
                _backgroundMusicSource.Stop();
                _backgroundMusicSource = null;
                _temporaryAudioListener = null;
                UnityEngine.Object.DestroyImmediate(musicObject);
            }
            else
            {
                _temporaryAudioListener = null;
            }
        }

        private static void RevealCompletedOutput()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                return;

            var outputFile = SessionState.GetString(CompletedOutputSessionKey, string.Empty);
            if (string.IsNullOrWhiteSpace(outputFile))
                return;

            SessionState.SetString(CompletedOutputSessionKey, string.Empty);
            var outputExists = File.Exists(outputFile);
            if (outputExists)
                EditorUtility.RevealInFinder(outputFile);
            else
                Debug.LogWarning("[PromotionalVideo] Expected output was not found: " + outputFile);

            if (SessionState.GetBool(QuitAfterCaptureSessionKey, false))
            {
                SessionState.SetBool(QuitAfterCaptureSessionKey, false);
                EditorApplication.delayCall += () => EditorApplication.Exit(outputExists ? 0 : 1);
            }
        }
    }
}
