using System;
using System.Collections.Generic;
using MetroReplay.Application;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class MetroTrainReplayPresenter : IDisposable
    {
        private const string TrainResourcePath = "MetroReplay/Trains/MetroTrain_StaticPrototype";
        private const string TrackResourcePath = "MetroReplay/Trains/MetroTrack_StaticPrototype";
        private const float SourceTrainLength = 106f;
        private const float SourceTrackLength = 118f;
        private const float TrackBedDrop = 0.44f;
        private readonly TrainReplaySampler _sampler;
        private readonly bool _animateWhenInactive;
        private readonly List<DoorLeaf> _doorLeaves = new List<DoorLeaf>(24);
        private readonly List<PlatformDoorLeaf> _platformDoorLeaves = new List<PlatformDoorLeaf>(12);
        private GameObject _train;
        private GameObject _track;
        private Material _doorMaterial;
        private Vector3 _platformPosition;
        private Vector3 _motionAxis;
        private float _travelDistance;

        public string Status { get; private set; } = "列车视觉未初始化";
        public bool IsVisible => _train != null && _train.activeSelf;
        public bool IsEnvironmentFallbackActive { get; private set; }

        public MetroTrainReplayPresenter(
            Transform parent,
            ReplayData data,
            bool animateWhenInactive = false)
        {
            if (parent == null)
                throw new ArgumentNullException(nameof(parent));
            if (data == null)
                throw new ArgumentNullException(nameof(data));

            _sampler = new TrainReplaySampler(data);
            _animateWhenInactive = animateWhenInactive;
            if (!TryGetPrimaryTrain(data, out var primaryTrain))
            {
                Status = "回放无列车快照";
                return;
            }
            if (!PlatformReplayLayoutResolver.TryResolve(data, out var layout))
            {
                Status = "缺少站台边缘，列车使用已禁用";
                return;
            }

            var trainPrefab = Resources.Load<GameObject>(TrainResourcePath);
            if (trainPrefab == null)
            {
                Status = "列车 Prefab 未进入 Resources";
                return;
            }

            _motionAxis = string.Equals(primaryTrain.Direction, "up", StringComparison.OrdinalIgnoreCase)
                ? layout.TrackAxis
                : -layout.TrackAxis;
            _platformPosition = layout.TrainCenter + Vector3.down * TrackBedDrop;
            _travelDistance = Mathf.Max(70f, layout.PlatformSpan + 36f);

            _train = UnityEngine.Object.Instantiate(trainPrefab, parent);
            _train.name = "MetroTrain_Replay";
            _train.transform.position = _platformPosition;
            _train.transform.rotation = Quaternion.LookRotation(-_motionAxis, Vector3.up);
            var trainScale = Mathf.Clamp((layout.PlatformSpan + 5f) / SourceTrainLength, 0.44f, 0.72f);
            _train.transform.localScale = new Vector3(1f, 1f, trainScale);

            var platformDirection = -layout.Outward;
            var rightWorld = _train.transform.rotation * Vector3.right;
            var doorSide = Vector3.Dot(rightWorld, platformDirection) >= 0f ? 1f : -1f;
            BuildAnimatedDoors(_train.transform, doorSide, layout);
            CollectPlatformDoorLeaves(parent, data);

            var trackPrefab = Resources.Load<GameObject>(TrackResourcePath);
            if (trackPrefab != null)
            {
                _track = UnityEngine.Object.Instantiate(trackPrefab, parent);
                _track.name = "MetroTrack_Replay";
                _track.transform.position = new Vector3(
                    layout.TrainCenter.x,
                    layout.LevelElevation - TrackBedDrop,
                    layout.TrainCenter.z);
                _track.transform.rotation = Quaternion.LookRotation(layout.TrackAxis, Vector3.up);
                var trackScale = Mathf.Clamp((layout.PlatformSpan + 12f) / SourceTrackLength, 0.46f, 0.78f);
                _track.transform.localScale = new Vector3(1f, 1f, trackScale);
            }

            _train.SetActive(false);
            Status = "列车候车中";
        }

        public void Sync(float time)
        {
            if (_train == null || !_sampler.TrySample(time, out var sample))
                return;

            IsEnvironmentFallbackActive = sample.Phase == TrainVisualPhase.Hidden
                && !sample.Visible
                && _animateWhenInactive
                && !_sampler.HasAuthoritativeMotion;
            if (IsEnvironmentFallbackActive
                && _sampler.TrySamplePresentationLoop(time, out var presentationSample))
            {
                ApplySample(presentationSample);
                UpdateStatus(presentationSample, true);
                return;
            }

            ApplySample(sample);
            UpdateStatus(sample, false);
        }

        private void ApplySample(TrainVisualSample sample)
        {
            _train.SetActive(sample.Visible);
            if (sample.Visible)
            {
                _train.transform.position = _platformPosition
                    + _motionAxis * (sample.NormalizedTravel * _travelDistance);
            }
            SetDoorProgress(sample.Visible ? sample.DoorOpenProgress : 0f);
        }

        private void UpdateStatus(TrainVisualSample sample, bool presentationOnly)
        {
            var suffix = presentationOnly ? "展示（非运营证据）" : string.Empty;
            switch (sample.Phase)
            {
                case TrainVisualPhase.Approaching:
                    Status = "列车进站" + suffix;
                    break;
                case TrainVisualPhase.Dwelling:
                    Status = (sample.DoorOpenProgress > 0.95f
                        ? "列车停站 · 车门开启"
                        : "列车停站 · 车门动作") + suffix;
                    break;
                case TrainVisualPhase.Departing:
                    Status = "列车出站" + suffix;
                    break;
                case TrainVisualPhase.Suspended:
                    Status = "列车服务暂停";
                    break;
                default:
                    Status = presentationOnly
                        ? "列车循环展示候场（非运营证据）"
                        : "列车未进站";
                    break;
            }
        }

        public void Dispose()
        {
            if (_train != null)
                DestroyRuntimeObject(_train);
            if (_track != null)
                DestroyRuntimeObject(_track);
            if (_doorMaterial != null)
                DestroyRuntimeObject(_doorMaterial);
            _doorLeaves.Clear();
            _platformDoorLeaves.Clear();
        }

        private void BuildAnimatedDoors(
            Transform trainRoot,
            float side,
            PlatformReplayLayout layout)
        {
            _doorMaterial = ReplayMaterialFactory.Create(
                "MetroTrain_AnimatedDoors",
                new Color(0.18f, 0.25f, 0.32f, 1f));
            for (var doorIndex = 0; doorIndex < layout.DoorCenters.Count; doorIndex++)
            {
                var localCenter = trainRoot.InverseTransformPoint(layout.DoorCenters[doorIndex]);
                CreateDoorLeaf(trainRoot, side, localCenter.z - 0.68f, -1f, doorIndex, 0, "L");
                CreateDoorLeaf(trainRoot, side, localCenter.z + 0.68f, 1f, doorIndex, 0, "R");
            }
        }

        private void CollectPlatformDoorLeaves(Transform parent, ReplayData data)
        {
            foreach (var entity in data.Entities)
            {
                if (!string.Equals(entity.Kind, "platform_edge", StringComparison.OrdinalIgnoreCase))
                    continue;
                var module = parent.Find(entity.Id);
                if (module == null)
                    continue;
                var left = module.Find("PlatformDoorLeaf_Left");
                var right = module.Find("PlatformDoorLeaf_Right");
                if (left != null)
                    _platformDoorLeaves.Add(new PlatformDoorLeaf(left, left.localPosition, -1f));
                if (right != null)
                    _platformDoorLeaves.Add(new PlatformDoorLeaf(right, right.localPosition, 1f));
            }
        }

        private void CreateDoorLeaf(
            Transform parent,
            float side,
            float localZ,
            float slideDirection,
            int carIndex,
            int doorIndex,
            string suffix)
        {
            var leaf = GameObject.CreatePrimitive(PrimitiveType.Cube);
            leaf.name = $"AnimatedDoor_C{carIndex + 1}_D{doorIndex + 1}_{suffix}";
            leaf.transform.SetParent(parent, false);
            leaf.transform.localPosition = new Vector3(side * 1.44f, 1.72f, localZ);
            leaf.transform.localScale = new Vector3(0.055f, 2.08f, 1.32f);
            var collider = leaf.GetComponent<Collider>();
            if (collider != null)
                DestroyRuntimeObject(collider);
            leaf.GetComponent<Renderer>().sharedMaterial = _doorMaterial;
            _doorLeaves.Add(new DoorLeaf(leaf.transform, leaf.transform.localPosition, slideDirection));
        }

        private static void DestroyRuntimeObject(UnityEngine.Object target)
        {
            if (UnityEngine.Application.isEditor)
                UnityEngine.Object.DestroyImmediate(target);
            else
                UnityEngine.Object.Destroy(target);
        }

        private void SetDoorProgress(float progress)
        {
            progress = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(progress));
            for (var i = 0; i < _doorLeaves.Count; i++)
            {
                var leaf = _doorLeaves[i];
                leaf.Transform.localPosition = leaf.ClosedPosition
                    + Vector3.forward * (leaf.SlideDirection * 1.18f * progress);
            }
            for (var i = 0; i < _platformDoorLeaves.Count; i++)
            {
                var leaf = _platformDoorLeaves[i];
                leaf.Transform.localPosition = leaf.ClosedPosition
                    + Vector3.right * (leaf.SlideDirection * 0.62f * progress);
            }
        }

        private static bool TryGetPrimaryTrain(ReplayData data, out TrainSnapshot train)
        {
            train = null;
            foreach (var frame in data.Frames)
            {
                foreach (var candidate in frame.Trains.Values)
                {
                    if (train == null || candidate.Id < train.Id)
                        train = candidate;
                }
                if (train != null)
                    return true;
            }
            return false;
        }

        private readonly struct DoorLeaf
        {
            public Transform Transform { get; }
            public Vector3 ClosedPosition { get; }
            public float SlideDirection { get; }

            public DoorLeaf(Transform transform, Vector3 closedPosition, float slideDirection)
            {
                Transform = transform;
                ClosedPosition = closedPosition;
                SlideDirection = slideDirection;
            }
        }

        private readonly struct PlatformDoorLeaf
        {
            public Transform Transform { get; }
            public Vector3 ClosedPosition { get; }
            public float SlideDirection { get; }

            public PlatformDoorLeaf(
                Transform transform,
                Vector3 closedPosition,
                float slideDirection)
            {
                Transform = transform;
                ClosedPosition = closedPosition;
                SlideDirection = slideDirection;
            }
        }
    }
}
