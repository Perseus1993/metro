using System;
using System.Collections.Generic;
using MetroReplay.Domain;
using UnityEngine;

namespace MetroReplay.Application
{
    public enum ElevatorVisualPhase
    {
        Waiting,
        Boarding,
        Traveling,
        Arrived,
        Repositioning
    }

    public readonly struct ElevatorVisualSample
    {
        public int EventId { get; }
        public Vector3 AnchorPosition { get; }
        public ElevatorVisualPhase Phase { get; }
        public float TravelProgress { get; }

        public ElevatorVisualSample(
            int eventId,
            Vector3 anchorPosition,
            ElevatorVisualPhase phase,
            float travelProgress)
        {
            EventId = eventId;
            AnchorPosition = anchorPosition;
            Phase = phase;
            TravelProgress = travelProgress;
        }
    }

    public sealed class ElevatorReplaySampler
    {
        private const float MinimumRepositionSeconds = 1f;
        private readonly ReplayData _data;
        private readonly List<FacilityServiceEvent> _events = new List<FacilityServiceEvent>();

        public bool HasEvents => _events.Count > 0;

        public ElevatorReplaySampler(ReplayData data, string facilityId)
        {
            _data = data ?? throw new ArgumentNullException(nameof(data));
            if (string.IsNullOrWhiteSpace(facilityId))
                throw new ArgumentException("Elevator facility id is required.", nameof(facilityId));

            foreach (var serviceEvent in data.FacilityEvents)
            {
                if (!string.Equals(
                    serviceEvent.FacilityKind,
                    "elevator",
                    StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                if (MatchesFacility(serviceEvent.FacilityId, facilityId))
                    _events.Add(serviceEvent);
            }
            _events.Sort((left, right) => left.StartTime.CompareTo(right.StartTime));
        }

        public bool TrySample(float time, out ElevatorVisualSample sample)
        {
            sample = default;
            if (_events.Count == 0)
                return false;

            time = Mathf.Clamp(time, 0f, _data.Duration);
            var first = _events[0];
            if (time < first.StartTime)
            {
                sample = CreateSample(
                    first,
                    StartAnchor(first),
                    ElevatorVisualPhase.Waiting,
                    0f);
                return true;
            }

            for (var index = 0; index < _events.Count; index++)
            {
                var current = _events[index];
                if (time <= current.EndTime)
                {
                    sample = SampleServiceEvent(current, time);
                    return true;
                }

                if (index + 1 >= _events.Count)
                    break;
                var next = _events[index + 1];
                if (time < next.StartTime)
                {
                    sample = SampleBetweenEvents(current, next, time);
                    return true;
                }
            }

            var last = _events[_events.Count - 1];
            sample = CreateSample(
                last,
                EndAnchor(last),
                ElevatorVisualPhase.Arrived,
                1f);
            return true;
        }

        private ElevatorVisualSample SampleServiceEvent(
            FacilityServiceEvent serviceEvent,
            float time)
        {
            var start = StartAnchor(serviceEvent);
            var end = EndAnchor(serviceEvent);
            var moveStart = Mathf.Clamp(
                serviceEvent.BoardEndTime,
                serviceEvent.StartTime,
                serviceEvent.EndTime);
            var moveEnd = Mathf.Clamp(
                serviceEvent.ArriveTime,
                moveStart,
                serviceEvent.EndTime);

            if (time <= moveStart)
            {
                return CreateSample(
                    serviceEvent,
                    start,
                    ElevatorVisualPhase.Boarding,
                    0f);
            }
            if (time >= moveEnd)
            {
                return CreateSample(
                    serviceEvent,
                    end,
                    ElevatorVisualPhase.Arrived,
                    1f);
            }

            var progress = Mathf.InverseLerp(moveStart, moveEnd, time);
            return CreateSample(
                serviceEvent,
                Vector3.LerpUnclamped(start, end, progress),
                ElevatorVisualPhase.Traveling,
                progress);
        }

        private ElevatorVisualSample SampleBetweenEvents(
            FacilityServiceEvent previous,
            FacilityServiceEvent next,
            float time)
        {
            var start = EndAnchor(previous);
            var end = StartAnchor(next);
            if ((end - start).sqrMagnitude < 0.0001f)
            {
                return CreateSample(
                    previous,
                    start,
                    ElevatorVisualPhase.Arrived,
                    1f);
            }

            var gapSeconds = Mathf.Max(0f, next.StartTime - previous.EndTime);
            var nextTravelSeconds = MovementDuration(next);
            if (nextTravelSeconds <= 0f)
                nextTravelSeconds = MovementDuration(previous);
            var repositionSeconds = Mathf.Min(
                gapSeconds,
                Mathf.Max(MinimumRepositionSeconds, nextTravelSeconds));
            var repositionStart = next.StartTime - repositionSeconds;
            if (repositionSeconds <= 0f || time <= repositionStart)
            {
                return CreateSample(
                    previous,
                    start,
                    ElevatorVisualPhase.Arrived,
                    1f);
            }

            var progress = Mathf.InverseLerp(repositionStart, next.StartTime, time);
            var easedProgress = Mathf.SmoothStep(0f, 1f, progress);
            return CreateSample(
                next,
                Vector3.LerpUnclamped(start, end, easedProgress),
                ElevatorVisualPhase.Repositioning,
                progress);
        }

        private Vector3 StartAnchor(FacilityServiceEvent serviceEvent)
        {
            return _data.ToWorld(
                serviceEvent.StartPosition.x,
                serviceEvent.StartPosition.y,
                serviceEvent.FromLevel,
                ReplaySampler.VerticalSurfaceOffset);
        }

        private Vector3 EndAnchor(FacilityServiceEvent serviceEvent)
        {
            return _data.ToWorld(
                serviceEvent.EndPosition.x,
                serviceEvent.EndPosition.y,
                serviceEvent.ToLevel,
                ReplaySampler.VerticalSurfaceOffset);
        }

        private static float MovementDuration(FacilityServiceEvent serviceEvent)
        {
            var moveStart = Mathf.Clamp(
                serviceEvent.BoardEndTime,
                serviceEvent.StartTime,
                serviceEvent.EndTime);
            var moveEnd = Mathf.Clamp(
                serviceEvent.ArriveTime,
                moveStart,
                serviceEvent.EndTime);
            return Mathf.Max(0f, moveEnd - moveStart);
        }

        private static ElevatorVisualSample CreateSample(
            FacilityServiceEvent serviceEvent,
            Vector3 position,
            ElevatorVisualPhase phase,
            float progress)
        {
            return new ElevatorVisualSample(
                serviceEvent.EventId,
                position,
                phase,
                Mathf.Clamp01(progress));
        }

        private static bool MatchesFacility(string eventFacilityId, string requestedFacilityId)
        {
            var eventId = RemoveKnownPrefix(eventFacilityId);
            var requestedId = RemoveKnownPrefix(requestedFacilityId);
            return string.Equals(eventId, requestedId, StringComparison.OrdinalIgnoreCase)
                || eventId.StartsWith(requestedId + ":", StringComparison.OrdinalIgnoreCase);
        }

        private static string RemoveKnownPrefix(string facilityId)
        {
            if (facilityId.StartsWith("vertical:", StringComparison.OrdinalIgnoreCase))
                return facilityId.Substring("vertical:".Length);
            if (facilityId.StartsWith("element:", StringComparison.OrdinalIgnoreCase))
                return facilityId.Substring("element:".Length);
            return facilityId;
        }
    }
}
