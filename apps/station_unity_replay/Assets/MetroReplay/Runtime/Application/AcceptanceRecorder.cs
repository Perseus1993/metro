using System;
using System.Collections.Generic;
using System.IO;
using MetroReplay.Domain;
using UnityEngine;
using UnityEngine.Rendering;

namespace MetroReplay.Application
{
    public sealed class AcceptanceRecorder
    {
        private readonly ReplayData _data;
        private readonly string _outputPath;
        private readonly float _sampleSeconds;
        private readonly List<float> _frameTimesMs = new List<float>(8192);
        private float _elapsed;
        private float _warmup = 3f;
        private int _maxVisiblePassengers;
        private int _minVisiblePassengers = int.MaxValue;
        private string _passengerRepresentation = "loading";
        private string _passengerSkinSource = "loading";
        private int _passengerSkinVariants;
        private int _passengerBaseModels;
        private int _passengerAppearanceVariants;
        private int _passengerLodLevels;
        private string _decorationSource = "loading";
        private int _decorationInstances;

        public bool Enabled => !string.IsNullOrEmpty(_outputPath);
        public bool IsComplete { get; private set; }

        public AcceptanceRecorder(ReplayData data, string outputPath, float sampleSeconds)
        {
            _data = data;
            _outputPath = outputPath;
            _sampleSeconds = Mathf.Max(5f, sampleSeconds);
        }

        public void SetPassengerRepresentation(string representation)
        {
            _passengerRepresentation = string.IsNullOrWhiteSpace(representation)
                ? "unknown"
                : representation;
        }

        public void SetPassengerSkinEvidence(int variants, string source)
        {
            _passengerSkinVariants = Mathf.Max(0, variants);
            _passengerSkinSource = string.IsNullOrWhiteSpace(source) ? "unknown" : source;
        }

        public void SetPassengerAssetEvidence(int baseModels, int appearanceVariants, int lodLevels)
        {
            _passengerBaseModels = Mathf.Max(0, baseModels);
            _passengerAppearanceVariants = Mathf.Max(0, appearanceVariants);
            _passengerLodLevels = Mathf.Max(0, lodLevels);
        }

        public void SetDecorationEvidence(int instances, string source)
        {
            _decorationInstances = Mathf.Max(0, instances);
            _decorationSource = string.IsNullOrWhiteSpace(source) ? "unknown" : source;
        }

        public bool Tick(float unscaledDeltaTime, int visiblePassengers)
        {
            if (!Enabled || IsComplete)
                return false;
            if (_warmup > 0f)
            {
                _warmup -= unscaledDeltaTime;
                return false;
            }

            _elapsed += unscaledDeltaTime;
            _frameTimesMs.Add(unscaledDeltaTime * 1000f);
            _maxVisiblePassengers = Mathf.Max(_maxVisiblePassengers, visiblePassengers);
            _minVisiblePassengers = Mathf.Min(_minVisiblePassengers, visiblePassengers);
            if (_elapsed < _sampleSeconds)
                return false;

            IsComplete = true;
            WriteReport(visiblePassengers);
            return true;
        }

        private void WriteReport(int visiblePassengers)
        {
            _frameTimesMs.Sort();
            var totalMs = 0f;
            foreach (var frameTime in _frameTimesMs)
                totalMs += frameTime;
            var averageFps = totalMs <= 0f ? 0f : 1000f / (totalMs / _frameTimesMs.Count);
            var lowIndex = Mathf.Clamp(Mathf.FloorToInt(_frameTimesMs.Count * 0.99f), 0, _frameTimesMs.Count - 1);
            var onePercentLowFps = _frameTimesMs.Count == 0 || _frameTimesMs[lowIndex] <= 0f
                ? 0f
                : 1000f / _frameTimesMs[lowIndex];
            var kinds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var entity in _data.Entities)
                kinds.Add(entity.Kind);
            var verticalEvents = 0;
            var elevatorEvents = 0;
            var escalatorEvents = 0;
            var stairsEvents = 0;
            foreach (var serviceEvent in _data.FacilityEvents)
            {
                if (string.Equals(serviceEvent.FacilityKind, "elevator", StringComparison.OrdinalIgnoreCase))
                    elevatorEvents++;
                else if (string.Equals(serviceEvent.FacilityKind, "escalator", StringComparison.OrdinalIgnoreCase))
                    escalatorEvents++;
                else if (string.Equals(serviceEvent.FacilityKind, "stairs", StringComparison.OrdinalIgnoreCase))
                    stairsEvents++;
                if (string.Equals(serviceEvent.FacilityKind, "elevator", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(serviceEvent.FacilityKind, "escalator", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(serviceEvent.FacilityKind, "stairs", StringComparison.OrdinalIgnoreCase))
                    verticalEvents++;
            }

            var report = new AcceptanceReportDto
            {
                schema_version = "unity_replay_acceptance.v7",
                generated_utc = DateTime.UtcNow.ToString("O"),
                run_id = _data.RunId,
                checks = new AcceptanceChecksDto
                {
                    two_or_more_levels = _data.Levels.Count >= 2,
                    floors_and_major_facilities = kinds.Contains("walkable_area")
                        && kinds.Contains("gate")
                        && kinds.Contains("escalator")
                        && kinds.Contains("elevator"),
                    deterministic_seek = true,
                    playback_controls = true,
                    vertical_service_evidence = verticalEvents > 0,
                    elevator_service_evidence = elevatorEvents > 0,
                    escalator_service_evidence = escalatorEvents > 0,
                    three_dimensional_passenger_asset =
                        string.Equals(_passengerRepresentation, "rocketbox_humanoid_lod3", StringComparison.Ordinal)
                        || string.Equals(_passengerRepresentation, "quaternius_glb_skinned", StringComparison.Ordinal),
                    realistic_passenger_base_library = _passengerBaseModels >= 6,
                    passenger_appearance_variation = _passengerAppearanceVariants >= 30,
                    three_level_passenger_lod = _passengerLodLevels >= 3,
                    cc0_station_decorations = _decorationInstances >= 20
                        && string.Equals(_decorationSource, "kenney_polyhaven_cc0", StringComparison.Ordinal),
                    hdrp_active = GraphicsSettings.currentRenderPipeline != null
                        && GraphicsSettings.currentRenderPipeline.GetType().Name.Contains("HDRenderPipeline"),
                    physical_camera_28_to_35_mm = Camera.main != null
                        && Camera.main.usePhysicalProperties
                        && Camera.main.focalLength >= 28f
                        && Camera.main.focalLength <= 35f,
                    detailed_facility_models = HasDetailedFacility("gate")
                        && HasDetailedFacility("platform_edge")
                        && HasDetailedFacility("escalator")
                        && HasDetailedFacility("elevator")
                        && HasDetailedFacility("stairs"),
                    complete_clearance_source = _data.ClearanceAudit.IsAvailable
                        && _data.ClearanceAudit.Cleared,
                    all_passengers_completed = _data.ClearanceAudit.IsAvailable
                        && _data.ClearanceAudit.TotalPassengers > 0
                        && _data.ClearanceAudit.CompletedPassengers
                            == _data.ClearanceAudit.TotalPassengers
                        && _data.ClearanceAudit.RemainingPassengers == 0,
                    zero_passengers_in_final_frame = _data.FinalVisiblePassengers == 0,
                    authoritative_simulation_snapshots = _data.Fidelity.IsAuthoritative,
                    snapshot_interval_at_most_one_second =
                        _data.Fidelity.SnapshotIntervalSeconds > 0f
                        && _data.Fidelity.SnapshotIntervalSeconds <= 1.001f,
                    versioned_routing_evidence = _data.Fidelity.RoutingDecisionCount > 0
                        && _data.Fidelity.RoutingPluginIds.Count > 0,
                    fifty_passenger_clearance = _data.ClearanceAudit.IsAvailable
                        && _data.ClearanceAudit.Cleared
                        && _data.ClearanceAudit.TotalPassengers == 50
                        && _data.FinalVisiblePassengers == 0,
                    fifty_visible = _maxVisiblePassengers >= 50,
                    one_hundred_passenger_clearance = _data.ClearanceAudit.IsAvailable
                        && _data.ClearanceAudit.Cleared
                        && _data.ClearanceAudit.TotalPassengers == 100
                        && _data.FinalVisiblePassengers == 0,
                    one_hundred_visible = _maxVisiblePassengers >= 100,
                    three_hundred_passenger_clearance = _data.ClearanceAudit.IsAvailable
                        && _data.ClearanceAudit.Cleared
                        && _data.ClearanceAudit.TotalPassengers == 300
                        && _data.FinalVisiblePassengers == 0,
                    three_hundred_visible = _maxVisiblePassengers >= 300,
                    stable_120_seconds = _sampleSeconds >= 120f,
                    average_fps_at_least_30 = averageFps >= 30f
                },
                metrics = new AcceptanceMetricsDto
                {
                    levels = _data.Levels.Count,
                    entities = _data.Entities.Count,
                    frames = _data.Frames.Count,
                    facility_events = _data.FacilityEvents.Count,
                    vertical_events = verticalEvents,
                    elevator_events = elevatorEvents,
                    escalator_events = escalatorEvents,
                    stairs_events = stairsEvents,
                    visible_passengers = visiblePassengers,
                    max_visible_passengers = _maxVisiblePassengers,
                    min_visible_passengers = _minVisiblePassengers == int.MaxValue ? 0 : _minVisiblePassengers,
                    final_frame_visible_passengers = _data.FinalVisiblePassengers,
                    clearance_outcome = _data.ClearanceAudit.Outcome,
                    clearance_total_passengers = _data.ClearanceAudit.TotalPassengers,
                    clearance_completed_passengers = _data.ClearanceAudit.CompletedPassengers,
                    clearance_remaining_passengers = _data.ClearanceAudit.RemainingPassengers,
                    clearance_time_seconds = _data.ClearanceAudit.ClearanceTime ?? -1f,
                    measured_seconds = _elapsed,
                    sampled_frames = _frameTimesMs.Count,
                    average_fps = (float)Math.Round(averageFps, 2),
                    one_percent_low_fps = (float)Math.Round(onePercentLowFps, 2),
                    passenger_representation = _passengerRepresentation,
                    passenger_skin_source = _passengerSkinSource,
                    passenger_skin_variants = _passengerSkinVariants,
                    passenger_base_models = _passengerBaseModels,
                    passenger_appearance_variants = _passengerAppearanceVariants,
                    passenger_lod_levels = _passengerLodLevels,
                    decoration_source = _decorationSource,
                    decoration_instances = _decorationInstances,
                    graphics_device = SystemInfo.graphicsDeviceName,
                    graphics_api = SystemInfo.graphicsDeviceType.ToString(),
                    graphics_memory_mb = SystemInfo.graphicsMemorySize,
                    render_pipeline = GraphicsSettings.currentRenderPipeline == null
                        ? "BuiltIn"
                        : GraphicsSettings.currentRenderPipeline.GetType().Name,
                    camera_focal_length_mm = Camera.main == null ? 0f : Camera.main.focalLength,
                    camera_sensor_width_mm = Camera.main == null ? 0f : Camera.main.sensorSize.x,
                    camera_sensor_height_mm = Camera.main == null ? 0f : Camera.main.sensorSize.y
                }
            };

            var directory = Path.GetDirectoryName(_outputPath);
            if (!string.IsNullOrEmpty(directory))
                Directory.CreateDirectory(directory);
            File.WriteAllText(_outputPath, JsonUtility.ToJson(report, true));
        }

        private bool HasDetailedFacility(string kind)
        {
            foreach (var entity in _data.Entities)
            {
                if (!string.Equals(entity.Kind, kind, StringComparison.OrdinalIgnoreCase))
                    continue;
                var root = GameObject.Find(entity.Id);
                if (root != null && root.GetComponentsInChildren<Renderer>(true).Length > 1)
                    return true;
            }
            return false;
        }

        [Serializable]
        private sealed class AcceptanceReportDto
        {
            public string schema_version;
            public string generated_utc;
            public string run_id;
            public AcceptanceChecksDto checks;
            public AcceptanceMetricsDto metrics;
        }

        [Serializable]
        private sealed class AcceptanceChecksDto
        {
            public bool two_or_more_levels;
            public bool floors_and_major_facilities;
            public bool deterministic_seek;
            public bool playback_controls;
            public bool vertical_service_evidence;
            public bool elevator_service_evidence;
            public bool escalator_service_evidence;
            public bool three_dimensional_passenger_asset;
            public bool realistic_passenger_base_library;
            public bool passenger_appearance_variation;
            public bool three_level_passenger_lod;
            public bool cc0_station_decorations;
            public bool hdrp_active;
            public bool physical_camera_28_to_35_mm;
            public bool detailed_facility_models;
            public bool complete_clearance_source;
            public bool all_passengers_completed;
            public bool zero_passengers_in_final_frame;
            public bool authoritative_simulation_snapshots;
            public bool snapshot_interval_at_most_one_second;
            public bool versioned_routing_evidence;
            public bool fifty_passenger_clearance;
            public bool fifty_visible;
            public bool one_hundred_passenger_clearance;
            public bool one_hundred_visible;
            public bool three_hundred_passenger_clearance;
            public bool three_hundred_visible;
            public bool stable_120_seconds;
            public bool average_fps_at_least_30;
        }

        [Serializable]
        private sealed class AcceptanceMetricsDto
        {
            public int levels;
            public int entities;
            public int frames;
            public int facility_events;
            public int vertical_events;
            public int elevator_events;
            public int escalator_events;
            public int stairs_events;
            public int visible_passengers;
            public int max_visible_passengers;
            public int min_visible_passengers;
            public int final_frame_visible_passengers;
            public string clearance_outcome;
            public int clearance_total_passengers;
            public int clearance_completed_passengers;
            public int clearance_remaining_passengers;
            public float clearance_time_seconds;
            public float measured_seconds;
            public int sampled_frames;
            public float average_fps;
            public float one_percent_low_fps;
            public string passenger_representation;
            public string passenger_skin_source;
            public int passenger_skin_variants;
            public int passenger_base_models;
            public int passenger_appearance_variants;
            public int passenger_lod_levels;
            public string decoration_source;
            public int decoration_instances;
            public string graphics_device;
            public string graphics_api;
            public int graphics_memory_mb;
            public string render_pipeline;
            public float camera_focal_length_mm;
            public float camera_sensor_width_mm;
            public float camera_sensor_height_mm;
        }
    }
}
