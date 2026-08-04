using System;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Application
{
    public enum TrainVisualPhase
    {
        Hidden,
        Approaching,
        Dwelling,
        Departing,
        Suspended
    }

    public readonly struct TrainVisualSample
    {
        public int TrainId { get; }
        public string PlatformId { get; }
        public string Direction { get; }
        public TrainVisualPhase Phase { get; }
        public bool Visible { get; }
        public float NormalizedTravel { get; }
        public float DoorOpenProgress { get; }
        public int CurrentLoadPersons { get; }

        public TrainVisualSample(
            int trainId,
            string platformId,
            string direction,
            TrainVisualPhase phase,
            bool visible,
            float normalizedTravel,
            float doorOpenProgress,
            int currentLoadPersons)
        {
            TrainId = trainId;
            PlatformId = platformId;
            Direction = direction;
            Phase = phase;
            Visible = visible;
            NormalizedTravel = normalizedTravel;
            DoorOpenProgress = doorOpenProgress;
            CurrentLoadPersons = currentLoadPersons;
        }
    }

    public sealed class TrainReplaySampler
    {
        private const float ApproachSeconds = 15f;
        private const float DepartureSeconds = 12f;
        private const float DoorMotionSeconds = 1.25f;
        private const float PresentationDwellSeconds = 10f;
        private const float PresentationHiddenSeconds = 8f;
        private const float PresentationCycleSeconds =
            ApproachSeconds + PresentationDwellSeconds + DepartureSeconds + PresentationHiddenSeconds;
        private readonly ReplayData _data;

        public bool HasAuthoritativeMotion { get; }

        public TrainReplaySampler(ReplayData data)
        {
            _data = data ?? throw new ArgumentNullException(nameof(data));
            foreach (var frame in data.Frames)
            {
                foreach (var train in frame.Trains.Values)
                {
                    if (string.Equals(train.State, "boarding", StringComparison.OrdinalIgnoreCase)
                        || train.DepartureElapsedSeconds.HasValue)
                    {
                        HasAuthoritativeMotion = true;
                        return;
                    }
                }
            }
        }

        public bool TrySample(float time, out TrainVisualSample sample)
        {
            sample = default;
            if (_data.Frames.Count == 0)
                return false;

            time = Mathf.Clamp(time, 0f, _data.Duration);
            var frameIndex = LocateFrameAtOrBefore(time);
            if (!TryGetPrimaryTrain(_data.Frames[frameIndex], out var train))
                return false;

            if (train.ServiceSuspended)
            {
                sample = CreateSample(train, TrainVisualPhase.Suspended, false, 0f, 0f);
                return true;
            }

            if (string.Equals(train.State, "boarding", StringComparison.OrdinalIgnoreCase))
            {
                var segmentStart = FindStateSegmentStart(frameIndex, train.Id, train.State);
                var segmentEnd = FindStateSegmentEnd(frameIndex, train.Id, train.State);
                var openProgress = Mathf.Clamp01((time - segmentStart) / DoorMotionSeconds);
                if (segmentEnd.HasValue)
                    openProgress = Mathf.Min(
                        openProgress,
                        Mathf.Clamp01((segmentEnd.Value - time) / DoorMotionSeconds));
                sample = CreateSample(
                    train,
                    TrainVisualPhase.Dwelling,
                    true,
                    0f,
                    openProgress);
                return true;
            }

            var elapsedSinceFrame = Mathf.Max(0f, time - _data.Frames[frameIndex].Time);
            if (train.DepartureElapsedSeconds.HasValue)
            {
                var departureElapsed = train.DepartureElapsedSeconds.Value + elapsedSinceFrame;
                if (departureElapsed <= DepartureSeconds)
                {
                    var progress = Mathf.SmoothStep(0f, 1f, departureElapsed / DepartureSeconds);
                    sample = CreateSample(
                        train,
                        TrainVisualPhase.Departing,
                        true,
                        progress,
                        0f);
                    return true;
                }
            }

            if (TryFindNextBoardingFrame(
                frameIndex,
                train.Id,
                train.CancelledTrains,
                out var arrivalTime))
            {
                var timeUntilArrival = arrivalTime - time;
                if (timeUntilArrival >= 0f && timeUntilArrival <= ApproachSeconds)
                {
                    var progress = Mathf.SmoothStep(
                        0f,
                        1f,
                        1f - timeUntilArrival / ApproachSeconds);
                    sample = CreateSample(
                        train,
                        TrainVisualPhase.Approaching,
                        true,
                        progress - 1f,
                        0f);
                    return true;
                }
            }

            sample = CreateSample(train, TrainVisualPhase.Hidden, false, 0f, 0f);
            return true;
        }

        public bool TrySamplePresentationLoop(float time, out TrainVisualSample sample)
        {
            sample = default;
            if (_data.Frames.Count == 0)
                return false;

            time = Mathf.Clamp(time, 0f, _data.Duration);
            var frameIndex = LocateFrameAtOrBefore(time);
            if (!TryGetPrimaryTrain(_data.Frames[frameIndex], out var train))
                return false;

            var cycleTime = Mathf.Repeat(time, PresentationCycleSeconds);
            if (cycleTime < ApproachSeconds)
            {
                var progress = Mathf.SmoothStep(0f, 1f, cycleTime / ApproachSeconds);
                sample = CreateSample(
                    train,
                    TrainVisualPhase.Approaching,
                    true,
                    progress - 1f,
                    0f);
                return true;
            }

            var dwellEnd = ApproachSeconds + PresentationDwellSeconds;
            if (cycleTime < dwellEnd)
            {
                var dwellTime = cycleTime - ApproachSeconds;
                var openProgress = Mathf.Clamp01(dwellTime / DoorMotionSeconds);
                var closeProgress = Mathf.Clamp01(
                    (PresentationDwellSeconds - dwellTime) / DoorMotionSeconds);
                sample = CreateSample(
                    train,
                    TrainVisualPhase.Dwelling,
                    true,
                    0f,
                    Mathf.Min(openProgress, closeProgress));
                return true;
            }

            var departureEnd = dwellEnd + DepartureSeconds;
            if (cycleTime < departureEnd)
            {
                var progress = Mathf.SmoothStep(
                    0f,
                    1f,
                    (cycleTime - dwellEnd) / DepartureSeconds);
                sample = CreateSample(
                    train,
                    TrainVisualPhase.Departing,
                    true,
                    progress,
                    0f);
                return true;
            }

            sample = CreateSample(train, TrainVisualPhase.Hidden, false, 0f, 0f);
            return true;
        }

        private int LocateFrameAtOrBefore(float time)
        {
            var low = 0;
            var high = _data.Frames.Count - 1;
            while (low <= high)
            {
                var middle = low + (high - low) / 2;
                if (_data.Frames[middle].Time <= time)
                    low = middle + 1;
                else
                    high = middle - 1;
            }
            return Mathf.Clamp(high, 0, _data.Frames.Count - 1);
        }

        private float FindStateSegmentStart(int frameIndex, int trainId, string state)
        {
            var first = frameIndex;
            while (first > 0
                && TryGetTrain(_data.Frames[first - 1], trainId, out var previous)
                && string.Equals(previous.State, state, StringComparison.OrdinalIgnoreCase))
            {
                first--;
            }
            return _data.Frames[first].Time;
        }

        private float? FindStateSegmentEnd(int frameIndex, int trainId, string state)
        {
            for (var i = frameIndex + 1; i < _data.Frames.Count; i++)
            {
                if (!TryGetTrain(_data.Frames[i], trainId, out var candidate)
                    || !string.Equals(candidate.State, state, StringComparison.OrdinalIgnoreCase))
                {
                    return _data.Frames[i].Time;
                }
            }
            return null;
        }

        private bool TryFindNextBoardingFrame(
            int frameIndex,
            int trainId,
            int cancelledTrains,
            out float arrivalTime)
        {
            for (var i = frameIndex + 1; i < _data.Frames.Count; i++)
            {
                if (!TryGetTrain(_data.Frames[i], trainId, out var candidate))
                    continue;
                if (candidate.ServiceSuspended)
                    break;
                if (string.Equals(candidate.State, "boarding", StringComparison.OrdinalIgnoreCase))
                {
                    arrivalTime = _data.Frames[i].Time;
                    return true;
                }
                if (candidate.CancelledTrains > cancelledTrains)
                    break;
            }
            arrivalTime = 0f;
            return false;
        }

        private static bool TryGetPrimaryTrain(ReplayFrame frame, out TrainSnapshot train)
        {
            train = null;
            foreach (var candidate in frame.Trains.Values)
            {
                if (train == null || candidate.Id < train.Id)
                    train = candidate;
            }
            return train != null;
        }

        private static bool TryGetTrain(ReplayFrame frame, int trainId, out TrainSnapshot train)
        {
            return frame.Trains.TryGetValue(trainId, out train);
        }

        private static TrainVisualSample CreateSample(
            TrainSnapshot train,
            TrainVisualPhase phase,
            bool visible,
            float normalizedTravel,
            float doorOpenProgress)
        {
            return new TrainVisualSample(
                train.Id,
                train.PlatformId,
                train.Direction,
                phase,
                visible,
                normalizedTravel,
                doorOpenProgress,
                train.CurrentLoadPersons);
        }
    }
}
