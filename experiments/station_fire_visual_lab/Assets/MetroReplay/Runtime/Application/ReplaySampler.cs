using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Application
{
    public sealed class ReplaySampler
    {
        public const float FloorSurfaceOffset = 0.03f;
        public const float VerticalSurfaceOffset = 0.15f;

        private readonly ReplayData _data;
        private readonly HashSet<int> _activeIds = new HashSet<int>();
        private readonly List<int> _sortedIds = new List<int>();

        public ReplaySampler(ReplayData data)
        {
            _data = data ?? throw new ArgumentNullException(nameof(data));
        }

        public void Sample(float time, List<PassengerPose> destination)
        {
            if (destination == null)
                throw new ArgumentNullException(nameof(destination));
            destination.Clear();
            if (_data.Frames.Count == 0 && _data.FacilityEvents.Count == 0)
                return;

            time = Mathf.Clamp(time, 0f, _data.Duration);
            LocateFrames(time, out var before, out var after);

            _activeIds.Clear();
            if (before != null)
            {
                foreach (var id in before.Passengers.Keys)
                    _activeIds.Add(id);
            }
            if (after != null)
            {
                foreach (var id in after.Passengers.Keys)
                    _activeIds.Add(id);
            }
            foreach (var serviceEvent in _data.FacilityEvents)
            {
                if (time + 0.0001f < serviceEvent.StartTime || time - 0.0001f > serviceEvent.EndTime)
                    continue;
                foreach (var id in serviceEvent.PassengerIds)
                    _activeIds.Add(id);
            }

            _sortedIds.Clear();
            _sortedIds.AddRange(_activeIds);
            _sortedIds.Sort();
            foreach (var id in _sortedIds)
            {
                var activeEvent = FindActiveEvent(id, time);
                if (activeEvent != null)
                {
                    destination.Add(SampleFacilityEvent(activeEvent, id, time, before, after));
                    continue;
                }

                if (TrySampleSnapshots(id, time, before, after, out var pose))
                    destination.Add(pose);
            }
        }

        private FacilityServiceEvent FindActiveEvent(int passengerId, float time)
        {
            foreach (var serviceEvent in _data.FacilityEvents)
            {
                if (time + 0.0001f < serviceEvent.StartTime)
                    break;
                if (time - 0.0001f <= serviceEvent.EndTime && serviceEvent.ContainsPassenger(passengerId))
                    return serviceEvent;
            }
            return null;
        }

        private PassengerPose SampleFacilityEvent(
            FacilityServiceEvent serviceEvent,
            int passengerId,
            float time,
            ReplayFrame before,
            ReplayFrame after)
        {
            var fallback = FindSnapshot(passengerId, before) ?? FindSnapshot(passengerId, after);
            var fromLevel = string.IsNullOrEmpty(serviceEvent.FromLevel)
                ? fallback?.LevelId ?? _data.Levels[0].Id
                : serviceEvent.FromLevel;
            var toLevel = string.IsNullOrEmpty(serviceEvent.ToLevel) ? fromLevel : serviceEvent.ToLevel;
            var isElevator = string.Equals(serviceEvent.FacilityKind, "elevator", StringComparison.OrdinalIgnoreCase);
            var isVertical = isElevator
                || string.Equals(serviceEvent.FacilityKind, "escalator", StringComparison.OrdinalIgnoreCase)
                || string.Equals(serviceEvent.FacilityKind, "stairs", StringComparison.OrdinalIgnoreCase);

            float progress;
            string levelId;
            if (isElevator)
            {
                var moveStart = Mathf.Clamp(serviceEvent.BoardEndTime, serviceEvent.StartTime, serviceEvent.EndTime);
                var moveEnd = Mathf.Clamp(serviceEvent.ArriveTime, moveStart, serviceEvent.EndTime);
                if (time <= moveStart)
                    progress = 0f;
                else if (time >= moveEnd)
                    progress = 1f;
                else
                    progress = Mathf.InverseLerp(moveStart, moveEnd, time);
                levelId = progress < 0.5f ? fromLevel : toLevel;
            }
            else
            {
                progress = Mathf.InverseLerp(serviceEvent.StartTime, serviceEvent.EndTime, time);
                levelId = progress < 0.5f ? fromLevel : toLevel;
            }

            var start = _data.ToWorld(
                serviceEvent.StartPosition.x,
                serviceEvent.StartPosition.y,
                fromLevel,
                VerticalSurfaceOffset);
            var end = _data.ToWorld(
                serviceEvent.EndPosition.x,
                serviceEvent.EndPosition.y,
                toLevel,
                VerticalSurfaceOffset);
            Vector3 position;
            Vector3 forward;
            if (isElevator)
            {
                position = Vector3.LerpUnclamped(start, end, progress);
                forward = end - start;
            }
            else if (isVertical)
            {
                var route = VerticalFacilityRouteResolver.Resolve(
                    serviceEvent.FacilityKind, start, end);
                position = route.Sample(start, progress);
                var probeProgress = Mathf.Min(1f, progress + 0.01f);
                var probe = route.Sample(start, probeProgress);
                forward = probe - position;
                if (forward.sqrMagnitude < 0.001f)
                    forward = position - route.Sample(start, Mathf.Max(0f, progress - 0.01f));
            }
            else
            {
                position = Vector3.LerpUnclamped(start, end, progress);
                forward = end - start;
            }
            forward.y = 0f;
            return new PassengerPose(
                passengerId,
                position,
                forward,
                levelId,
                fallback?.State ?? "in_service",
                isVertical,
                fallback?.Intent ?? string.Empty);
        }

        private bool TrySampleSnapshots(
            int passengerId,
            float time,
            ReplayFrame before,
            ReplayFrame after,
            out PassengerPose pose)
        {
            var left = FindSnapshot(passengerId, before);
            var right = FindSnapshot(passengerId, after);
            if (left == null && right == null)
            {
                pose = default;
                return false;
            }

            if (left == null)
            {
                // Do not show an agent before its first authoritative frame.
                if (after != null && time + 0.0001f < after.Time)
                {
                    pose = default;
                    return false;
                }
                pose = SnapshotPose(right);
                return true;
            }

            if (right == null || before == null || after == null || Mathf.Abs(after.Time - before.Time) < 0.0001f)
            {
                pose = SnapshotPose(left);
                return true;
            }

            var progress = Mathf.InverseLerp(before.Time, after.Time, time);
            var start = _data.ToWorld(left.X, left.Y, left.LevelId, FloorSurfaceOffset);
            var end = _data.ToWorld(right.X, right.Y, right.LevelId, FloorSurfaceOffset);
            var position = Vector3.LerpUnclamped(start, end, progress);
            var forward = end - start;
            forward.y = 0f;
            pose = new PassengerPose(
                passengerId,
                position,
                forward,
                progress < 0.5f ? left.LevelId : right.LevelId,
                progress < 0.5f ? left.State : right.State,
                !string.Equals(left.LevelId, right.LevelId, StringComparison.Ordinal),
                progress < 0.5f ? left.Intent : right.Intent);
            return true;
        }

        private PassengerPose SnapshotPose(PassengerSnapshot snapshot)
        {
            return new PassengerPose(
                snapshot.Id,
                _data.ToWorld(snapshot.X, snapshot.Y, snapshot.LevelId, FloorSurfaceOffset),
                Vector3.forward,
                snapshot.LevelId,
                snapshot.State,
                false,
                snapshot.Intent);
        }

        private static PassengerSnapshot FindSnapshot(int passengerId, ReplayFrame frame)
        {
            if (frame != null && frame.Passengers.TryGetValue(passengerId, out var snapshot))
                return snapshot;
            return null;
        }

        private void LocateFrames(float time, out ReplayFrame before, out ReplayFrame after)
        {
            var frames = _data.Frames;
            if (frames.Count == 0)
            {
                before = null;
                after = null;
                return;
            }
            if (time <= frames[0].Time)
            {
                before = frames[0];
                after = frames[0];
                return;
            }
            if (time >= frames[frames.Count - 1].Time)
            {
                before = frames[frames.Count - 1];
                after = before;
                return;
            }

            var low = 0;
            var high = frames.Count - 1;
            while (low <= high)
            {
                var middle = low + (high - low) / 2;
                if (frames[middle].Time <= time)
                    low = middle + 1;
                else
                    high = middle - 1;
            }

            var leftIndex = Mathf.Clamp(high, 0, frames.Count - 1);
            if (Mathf.Abs(frames[leftIndex].Time - time) < 0.0001f)
            {
                before = frames[leftIndex];
                after = before;
                return;
            }
            before = frames[leftIndex];
            after = frames[Mathf.Min(leftIndex + 1, frames.Count - 1)];
        }
    }
}
